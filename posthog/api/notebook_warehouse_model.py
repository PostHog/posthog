from uuid import UUID, uuid4

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, Throttled
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.auth import SessionAuthentication
from posthog.exceptions import Conflict
from posthog.models import User
from posthog.rate_limit import RunNotebookModelRateThrottle

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.data_modeling.backend.facade.api import (
    MaterializationAlreadyRunningError,
    MaterializationForbiddenError,
    MaterializationRanRecentlyError,
    declare_notebook_model,
    notebook_dag_status,
    notebook_dag_workflow_id,
    owned_notebook_model,
    run_related_node_materializations,
)
from products.data_modeling.backend.facade.models import DataModelingJob
from products.notebooks.backend.facade.api import get_notebook
from products.notebooks.backend.facade.contracts import NotebookData
from products.notebooks.backend.facade.notebook_run import read_notebook_run
from products.notebooks.backend.facade.warehouse_model import authorize_model_publication, notebook_model_digest
from products.notebooks.backend.presentation.run_serializers import NotebookRunCellSerializer


class DeclareNotebookModelSerializer(serializers.Serializer):
    daily_refresh = serializers.BooleanField(
        default=True,
        help_text="Request a daily refresh. Set false to run manually or when a downstream model needs fresh data.",
    )
    table_name = serializers.RegexField(
        r"^[A-Za-z_][A-Za-z0-9_]*\Z", max_length=128, help_text="Name for the published warehouse table."
    )
    output_cell = serializers.CharField(
        max_length=128, help_text="Stable node ID of the SQL or Python cell that produces the table."
    )
    upstream_node_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=100,
        allow_empty=True,
        help_text="Modeling DAG node IDs which must succeed before the notebook runs.",
    )


class NotebookModelSerializer(serializers.Serializer):
    node_id = serializers.UUIDField(help_text="Modeling DAG node ID for running or inspecting the model.")
    table_id = serializers.UUIDField(
        allow_null=True, help_text="Warehouse table ID after the first successful publication."
    )
    latest_run_id = serializers.UUIDField(
        allow_null=True, help_text="Most recent notebook run. Use notebook run status to inspect cell failures."
    )
    published_run_id = serializers.UUIDField(
        allow_null=True, help_text="Notebook run that produced the currently published rows."
    )


class NotebookModelRunSerializer(NotebookModelSerializer):
    dag_run_id = serializers.UUIDField(help_text="Pass this ID to the status tool to follow this specific DAG run.")


class NotebookDagStatusSerializer(serializers.Serializer):
    status = serializers.CharField(
        help_text="DAG execution state, including whether upstream failures skipped this model."
    )
    reason = serializers.CharField(allow_null=True, help_text="Reason the model failed or was skipped.")


class NotebookModelStatusSerializer(NotebookModelSerializer):
    dag = NotebookDagStatusSerializer(allow_null=True, help_text="State of the requested DAG run.")
    status = serializers.CharField(allow_null=True, help_text="Latest modeling job status, including publication.")
    error = serializers.CharField(allow_null=True, help_text="Latest modeling job failure, if any.")
    cells = NotebookRunCellSerializer(many=True, help_text="Cells in execution order, including any failure.")


@extend_schema(tags=["notebooks"])
class NotebookWarehouseModelViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    scope_object = "notebook"
    lookup_field = "short_id"
    path_parameters = {"short_id": str, "node_id": UUID}
    serializer_class = NotebookModelSerializer

    def read_object(self) -> NotebookData | None:
        return get_notebook(self.team_id, self.kwargs["short_id"])

    def object_access_ref(self, record: NotebookData) -> ObjectAccessRef:
        return ObjectAccessRef(
            resource="notebook", id=str(record.id), team_id=self.team_id, created_by_id=record.created_by_id
        )

    @extend_schema(
        operation_id="notebooks_warehouse_model_status",
        responses=NotebookModelStatusSerializer,
        parameters=[
            OpenApiParameter(
                "dag_run_id", OpenApiTypes.UUID, description="DAG run ID returned when you started this model."
            )
        ],
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path=r"warehouse_model/(?P<node_id>[0-9a-f-]{36})",
        required_scopes=["notebook:read", "query:read", "warehouse_table:read"],
    )
    def warehouse_model_status(self, request: Request, node_id: UUID, **kwargs: object) -> Response:
        notebook = self.get_object()
        user = authorize_model_publication(
            self.team_id, notebook.id, request.user if isinstance(request.user, User) else None
        )
        model = owned_notebook_model(self.team_id, notebook.id, node_id, user)
        status = (
            read_notebook_run(team_id=self.team_id, notebook_short_id=notebook.short_id, run_id=model.latest_run_id)
            if model.latest_run_id
            else None
        )
        job = (
            DataModelingJob.objects.filter(team_id=self.team_id, id=model.latest_run_id)
            .values("status", "error")
            .first()
        )
        request_id = request.query_params.get("dag_run_id")
        dag = (
            notebook_dag_status(self.team_id, model.node_id, serializers.UUIDField().run_validation(request_id))
            if request_id
            else None
        )
        return Response(
            NotebookModelStatusSerializer(
                {
                    **NotebookModelSerializer(model).data,
                    "dag": dag,
                    "cells": status["cells"] if status else [],
                    **(job or {"status": None, "error": None}),
                }
            ).data
        )

    @extend_schema(
        operation_id="notebooks_run_warehouse_model", request=None, responses={202: NotebookModelRunSerializer}
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path=r"warehouse_model/(?P<node_id>[0-9a-f-]{36})/run",
        required_scopes=["notebook:write", "query:read", "warehouse_table:write", "warehouse_view:write"],
    )
    def run_warehouse_model(self, request: Request, node_id: UUID, **kwargs: object) -> Response:
        notebook = self.get_object()
        user = authorize_model_publication(
            self.team_id, notebook.id, request.user if isinstance(request.user, User) else None
        )
        model = owned_notebook_model(self.team_id, notebook.id, node_id, user)
        RunNotebookModelRateThrottle().check(request, self)
        request_id = uuid4()
        try:
            run_related_node_materializations(
                self.team_id,
                node_id,
                direction="upstream",
                user=user,
                workflow_id=notebook_dag_workflow_id(self.team_id, model.node_id, request_id),
                from_browser_session=isinstance(request.successful_authenticator, SessionAuthentication),
            )
        except MaterializationForbiddenError as exc:
            raise PermissionDenied(str(exc)) from exc
        except MaterializationAlreadyRunningError as exc:
            raise Conflict(str(exc)) from exc
        except MaterializationRanRecentlyError as exc:
            raise Throttled(wait=exc.retry_after_seconds, detail=str(exc)) from exc
        return Response(
            NotebookModelRunSerializer({**NotebookModelSerializer(model).data, "dag_run_id": request_id}).data,
            status=202,
        )

    @extend_schema(
        operation_id="notebooks_declare_warehouse_model",
        request=DeclareNotebookModelSerializer,
        responses=NotebookModelSerializer,
    )
    @action(
        methods=["POST"],
        detail=True,
        url_path="warehouse_model",
        required_scopes=["notebook:write", "query:read", "warehouse_table:write", "warehouse_view:write"],
    )
    def declare_warehouse_model(self, request: Request, **kwargs: object) -> Response:
        notebook = self.get_object()
        if not isinstance(request.user, User):
            raise PermissionDenied("Sign in as a project member to declare a warehouse model.")
        user = request.user
        authorize_model_publication(self.team_id, notebook.id, user)
        serializer = DeclareNotebookModelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        digest = notebook_model_digest(self.team_id, notebook.id, values["output_cell"])
        model = declare_notebook_model(
            team=self.team,
            user=user,
            notebook_id=notebook.id,
            output_cell=values["output_cell"],
            definition_hash=digest,
            name=values["table_name"],
            upstream_node_ids=values["upstream_node_ids"],
            daily_refresh=values["daily_refresh"],
        )
        return Response(NotebookModelSerializer(model).data)
