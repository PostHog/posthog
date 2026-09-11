"""Read-side rendering of a saved query: run state, columns, and the list serializer."""

from datetime import datetime
from typing import Any, cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.schema import DataWarehouseManagedViewsetKind

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, serialize_fields

from posthog.api.shared import UserBasicSerializer
from posthog.models import User

from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.data_modeling.backend.facade.api import get_incremental_config
from products.data_modeling.backend.facade.models import DataModelingJob, DataModelingJobEngine, DataWarehouseSavedQuery

from . import sync_cadence, view_description


class DataWarehouseSavedQuerySerializerMixin:
    """Shared methods for DataWarehouseSavedQuery serializers.

    This mixin is intended to be used with serializers.ModelSerializer subclasses.
    """

    def _serving_run(self, view: DataWarehouseSavedQuery) -> DataModelingJob | None:
        """The newest materialization run that serves this view, or None if it has never run.

        Prefers the prefetched job so a list of views costs one query. Falls back to a lookup for
        the detail route, which has no prefetch.
        """
        try:
            jobs = view.jobs  # type: ignore[attr-defined]
            return jobs[0] if jobs else None
        except AttributeError:
            return (
                DataModelingJob.objects.filter(saved_query_id=view.id)
                .exclude(engine=DataModelingJobEngine.DUCKGRES)
                .order_by("-last_run_at")
                .first()
            )

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_run_at(self, view: DataWarehouseSavedQuery) -> datetime | None:
        run = self._serving_run(view)
        return run.last_run_at if run is not None else view.last_run_at

    @extend_schema_field(serializers.ChoiceField(choices=DataWarehouseSavedQuery.Status.choices, allow_null=True))
    def get_status(self, view: DataWarehouseSavedQuery) -> str | None:
        run = self._serving_run(view)
        if run is None:
            return view.status
        # Modified means "edited and not materialized since", which no run can express. A run that
        # happened after the edit answers it, so the column only wins while the edit is the newer fact.
        edited_since_the_run = (
            view.status == DataWarehouseSavedQuery.Status.MODIFIED
            and view.updated_at is not None
            and view.updated_at > run.last_run_at
        )
        return view.status if edited_since_the_run else run.status

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_latest_error(self, view: DataWarehouseSavedQuery) -> str | None:
        run = self._serving_run(view)
        return run.error if run is not None else view.latest_error

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_sync_frequency(self, schema: DataWarehouseSavedQuery):
        return sync_cadence.resolve_sync_frequency(self.root, schema)  # type: ignore[attr-defined]

    @extend_schema_field(serializers.BooleanField())
    def get_is_incremental(self, view: DataWarehouseSavedQuery) -> bool:
        return get_incremental_config(view) is not None

    @extend_schema_field(sync_cadence.SyncFrequencyBoundsSerializer())
    def get_sync_frequency_bounds(self, view: DataWarehouseSavedQuery) -> dict[str, Any]:
        from products.data_modeling.backend.facade.api import saved_query_target_bounds

        if view.managed_viewset is not None:
            return sync_cadence._unbounded_frequency_payload("managed_viewset")

        resolved = saved_query_target_bounds(view.team_id, view.pk)
        if resolved is None:
            return sync_cadence._unbounded_frequency_payload("no_node")
        visible = sync_cadence.visible_blocker_names(resolved, self.user_access_control, team_id=view.team_id)  # type: ignore[attr-defined]
        return sync_cadence._frequency_bounds_payload(resolved, visible)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_managed_viewset_kind(self, view: DataWarehouseSavedQuery) -> DataWarehouseManagedViewsetKind | None:
        return cast(DataWarehouseManagedViewsetKind, view.managed_viewset.kind) if view.managed_viewset else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_columns(self, view: DataWarehouseSavedQuery) -> list[SerializedField]:
        query = view.query or {}
        if not isinstance(query, dict) or "query" not in query:
            return []

        team_id = self.context["team_id"]  # type: ignore[attr-defined]
        database = self.context.get("database", None)  # type: ignore[attr-defined]
        if not database:
            database = Database.create_for(
                team_id=team_id,
                user=cast(User, self.context["request"].user),  # type: ignore[attr-defined]
            )

        context = HogQLContext(team_id=team_id, database=database)

        descriptions = view_description.view_annotation_map(view)
        fields = serialize_fields(view.hogql_definition().fields, context, view.name_chain, table_type="external")
        return [
            SerializedField(
                key=field.name,
                name=field.name,
                type=field.type,
                schema_valid=field.schema_valid,
                fields=field.fields,
                table=field.table,
                chain=field.chain,
                description=descriptions.get(field.name),
            )
            for field in fields
        ]


class DataWarehouseSavedQueryMinimalSerializer(
    DataWarehouseSavedQuerySerializerMixin, UserAccessControlSerializerMixin, serializers.ModelSerializer
):
    """Lightweight serializer for list views - excludes large query field to reduce memory usage."""

    created_by = UserBasicSerializer(read_only=True)
    columns = serializers.SerializerMethodField(read_only=True)
    description = view_description.ViewDescriptionField(
        read_only=True, help_text=view_description.VIEW_DESCRIPTION_HELP_TEXT
    )
    sync_frequency = serializers.SerializerMethodField()
    last_run_at = serializers.SerializerMethodField(read_only=True)
    status = serializers.SerializerMethodField(read_only=True)
    latest_error = serializers.SerializerMethodField(read_only=True)
    managed_viewset_kind = serializers.SerializerMethodField(read_only=True)
    folder_id = serializers.UUIDField(source="folder.id", read_only=True, allow_null=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True, allow_null=True)
    is_incremental = serializers.SerializerMethodField(
        read_only=True,
        help_text="Whether this view is set up to update incrementally. A run can still rebuild the "
        "whole table, for example on the first run or after the query changes.",
    )

    class Meta:
        model = DataWarehouseSavedQuery
        fields = [
            "id",
            "deleted",
            "name",
            "created_by",
            "created_at",
            "description",
            "sync_frequency",
            "columns",
            "status",
            "last_run_at",
            "managed_viewset_kind",
            "folder_id",
            "folder_name",
            "latest_error",
            "is_materialized",
            "is_incremental",
            "origin",
            "is_test",
            "expires_at",
            "user_access_level",
        ]
        read_only_fields = fields


class SavedQuerySuspensionSerializer(serializers.Serializer):
    at = serializers.DateTimeField(help_text="When materialization was suspended.")
    reason = serializers.CharField(help_text="Error from the materialization run that tripped suspension.")
    job_id = serializers.CharField(help_text="Materialization job that tripped suspension.")
