import csv
import uuid
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union, cast

from django.conf import settings
from django.db import DatabaseError
from django.db.models import OuterRef, Prefetch, QuerySet, Subquery, prefetch_related_objects

import structlog
from drf_spectacular.utils import extend_schema
from loginas.utils import is_impersonated_session
from prometheus_client import Counter
from pydantic import (
    BaseModel,
    Field,
    ValidationError as PydanticValidationError,
    model_validator,
)
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework_csv import renderers as csvrenderers

from posthog.schema import ActorsQuery, HogQLQuery

from posthog.hogql.constants import CSV_EXPORT_LIMIT
from posthog.hogql.context import HogQLContext

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.insight import capture_legacy_api_call
from posthog.api.person import get_funnel_actor_class
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action, get_target_entity
from posthog.clickhouse.client import sync_execute
from posthog.constants import (
    INSIGHT_FUNNELS,
    INSIGHT_LIFECYCLE,
    INSIGHT_STICKINESS,
    INSIGHT_TRENDS,
    LIMIT,
    OFFSET,
    PropertyOperatorType,
)
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Cohort, FeatureFlag, Person, User
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    dict_changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.cohort import DEFAULT_COHORT_INSERT_BATCH_SIZE, CohortOrEmpty
from posthog.models.cohort.calculation_history import CohortCalculationHistory
from posthog.models.cohort.util import get_all_cohort_dependencies, print_cohort_hogql_query
from posthog.models.cohort.validation import CohortTypeValidationSerializer
from posthog.models.feature_flag.flag_matching import (
    FeatureFlagMatcher,
    FlagsMatcherCache,
    get_feature_flag_hash_key_overrides,
)
from posthog.models.filters.filter import Filter
from posthog.models.filters.lifecycle_filter import LifecycleFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.person.person import READ_DB_FOR_PERSONS, PersonDistinctId
from posthog.models.person.sql import INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID, PERSON_STATIC_COHORT_TABLE
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT
from posthog.queries.actor_base_query import ActorBaseQuery, get_serialized_people
from posthog.queries.base import property_group_to_Q
from posthog.queries.person_query import PersonQuery
from posthog.queries.stickiness import StickinessActors
from posthog.queries.trends.lifecycle_actors import LifecycleActors
from posthog.queries.trends.trends_actors import TrendsActors
from posthog.queries.util import get_earliest_timestamp
from posthog.renderers import SafeJSONRenderer
from posthog.utils import format_query_params_absolute_url


class EventPropFilter(BaseModel, extra="forbid"):
    type: Literal["event", "element"]
    key: str
    value: Any
    operator: str | None = None


class HogQLFilter(BaseModel, extra="forbid"):
    type: Literal["hogql"]
    key: str
    value: Any | None = None


class BehavioralFilter(BaseModel, extra="forbid"):
    type: Literal["behavioral"]
    key: Union[str, int]  # action IDs can be ints
    value: str
    event_type: str
    time_value: int | None = None
    time_interval: str | None = None
    negation: bool = False
    operator: str | None = None
    operator_value: int | None = None
    seq_time_interval: str | None = None
    seq_time_value: int | None = None
    seq_event: Union[str, int] | None = None  # Allow both string and int for seq_event
    seq_event_type: str | None = None
    total_periods: int | None = None
    min_periods: int | None = None
    event_filters: list[Union[EventPropFilter, HogQLFilter]] | None = None
    explicit_datetime: str | None = None


class CohortFilter(BaseModel, extra="forbid"):
    type: Literal["cohort"]
    key: Literal["id"]
    value: int
    negation: bool = False


class PersonFilter(BaseModel, extra="forbid"):
    type: Literal["person"]
    key: str
    operator: str | None = None  # accept any legacy operator
    value: Any | None = None  # mostly likely it's list[str], str, or None
    negation: bool = False

    @model_validator(mode="after")
    def _missing_keys_check(self):
        missing: list[str] = []

        # value is required unless operator is an *is_set* variant
        if self.value is None and self.operator not in ("is_set", "is_not_set"):
            missing.append("value")

        # operator is required whenever value is supplied,
        # and also when both value & operator are missing
        if self.operator is None:
            missing.append("operator")

        if missing:
            raise ValueError(f"Missing required keys for person filter: {', '.join(missing)}")

        return self


PropertyFilter = Annotated[
    Union[BehavioralFilter, CohortFilter, PersonFilter],
    Field(discriminator="type"),
]

FilterOrGroup = Annotated[Union[PropertyFilter, "Group"], Field(discriminator="type")]


class Group(BaseModel, extra="forbid"):
    type: Literal["AND", "OR"]
    values: list[FilterOrGroup]


Group.model_rebuild()


class CohortFilters(BaseModel, extra="forbid"):
    properties: Group


API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER = Counter(
    "api_cohort_person_bytes_read_from_postgres",
    "An estimate of how many bytes we've read from postgres to service person cohort endpoint.",
    labelnames=[LABEL_TEAM_ID],
)

logger = structlog.get_logger(__name__)


class AddPersonsToStaticCohortRequestSerializer(serializers.Serializer):
    person_ids = serializers.ListField(
        child=serializers.UUIDField(), required=True, help_text="List of person UUIDs to add to the cohort"
    )


class RemovePersonRequestSerializer(serializers.Serializer):
    person_id = serializers.UUIDField(required=True, help_text="Person UUID to remove from the cohort")


class CohortCalculationHistorySerializer(serializers.ModelSerializer):
    duration_seconds = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()
    is_successful = serializers.ReadOnlyField()
    total_query_ms = serializers.ReadOnlyField()
    total_memory_mb = serializers.ReadOnlyField()
    total_read_rows = serializers.ReadOnlyField()
    total_written_rows = serializers.ReadOnlyField()
    main_query = serializers.ReadOnlyField()

    class Meta:
        model = CohortCalculationHistory
        fields = [
            "id",
            "filters",
            "count",
            "started_at",
            "finished_at",
            "queries",
            "error",
            "duration_seconds",
            "is_completed",
            "is_successful",
            "total_query_ms",
            "total_memory_mb",
            "total_read_rows",
            "total_written_rows",
            "main_query",
        ]


class CSVConfig:
    """Configuration constants for CSV processing"""

    PERSON_ID_HEADERS = ["person_id", "person-id", "Person .id"]
    DISTINCT_ID_HEADERS = ["distinct_id", "distinct-id"]
    EMAIL_HEADERS = ["email", "e-mail"]
    ENCODING = "utf-8"

    class ErrorMessages:
        EMPTY_FILE = "CSV file is empty. Please upload a CSV file with at least one row of data."
        MISSING_ID_COLUMN = "Multi-column CSV must contain at least one column with a supported ID header: 'person_id', 'Person .id' (PostHog export format), 'distinct_id', 'distinct-id', or 'email'. Found columns: {columns}"
        NO_VALID_IDS = "CSV file contains no valid person IDs, distinct IDs, or email addresses. Please ensure your file has data rows with person IDs, distinct IDs, or email addresses."
        ENCODING_ERROR = "CSV file encoding is not supported. Please save your file as UTF-8 and try again."
        FORMAT_ERROR = "CSV file format is invalid. Please check your file format and try again."
        GENERIC_ERROR = "An error occurred while processing your CSV file. Please try again or contact support if the problem persists."


class CohortSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    earliest_timestamp_func = get_earliest_timestamp
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    _create_static_person_ids = serializers.ListField(required=False, child=serializers.CharField(), write_only=True)

    # If this cohort is an exposure cohort for an experiment
    experiment_set: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(many=True, read_only=True)

    class Meta:
        model = Cohort
        fields = [
            "id",
            "name",
            "description",
            "groups",
            "deleted",
            "filters",
            "query",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "is_static",
            "cohort_type",
            "experiment_set",
            "_create_in_folder",
            "_create_static_person_ids",
        ]
        read_only_fields = [
            "id",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "errors_calculating",
            "count",
            "experiment_set",
        ]

    def validate_cohort_type(self, value):
        """Validate that the cohort type matches the filters"""
        if not value:
            return value

        cohort_data = {
            "cohort_type": value,
            "is_static": self.initial_data.get(
                "is_static", getattr(self.instance, "is_static", False) if self.instance else False
            ),
            "query": self.initial_data.get("query", getattr(self.instance, "query", None) if self.instance else None),
            "filters": self.initial_data.get(
                "filters", getattr(self.instance, "filters", None) if self.instance else None
            ),
        }

        type_serializer = CohortTypeValidationSerializer(data=cohort_data, team_id=self.context["team_id"])
        if not type_serializer.is_valid():
            # NB: Get the first error message, since it's the only one we're interested in
            if "cohort_type" in type_serializer.errors:
                raise ValidationError(type_serializer.errors["cohort_type"][0])
            raise ValidationError("Invalid cohort type for the given filters")

        return value

    def _handle_static(self, cohort: Cohort, context: dict, validated_data: dict, person_ids: list[str] | None) -> None:
        from posthog.tasks.calculate_cohort import (
            insert_cohort_from_feature_flag,
            insert_cohort_from_insight_filter,
            insert_cohort_from_query,
        )

        request = self.context["request"]
        if request.FILES.get("csv") or person_ids is not None:
            if person_ids is not None:
                uuids = [
                    str(uuid)
                    for uuid in Person.objects.db_manager(READ_DB_FOR_PERSONS)
                    .filter(team_id=self.context["team_id"], uuid__in=person_ids)
                    .values_list("uuid", flat=True)
                ]
                cohort.insert_users_list_by_uuid(uuids, team_id=self.context["team_id"])
            if request.FILES.get("csv"):
                self._calculate_static_by_csv(request.FILES["csv"], cohort)
        elif context.get("from_feature_flag_key"):
            insert_cohort_from_feature_flag.delay(cohort.pk, context["from_feature_flag_key"], self.context["team_id"])
        elif validated_data.get("query"):
            insert_cohort_from_query.delay(cohort.pk, self.context["team_id"])
        else:
            filter_data = request.GET.dict()
            existing_cohort_id = context.get("from_cohort_id")
            if existing_cohort_id:
                filter_data = {**filter_data, "from_cohort_id": existing_cohort_id}
            if filter_data:
                capture_legacy_api_call(request, self.context["get_team"]())
                insert_cohort_from_insight_filter.delay(cohort.pk, filter_data, self.context["team_id"])

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user

        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        if validated_data.get("query") and validated_data.get("filters"):
            raise ValidationError("Cannot set both query and filters at the same time.")
        person_ids = validated_data.pop("_create_static_person_ids", None)
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            self._handle_static(cohort, self.context, validated_data, person_ids)
        elif cohort.query is not None:
            raise ValidationError("Cannot create a dynamic cohort with a query. Set is_static to true.")
        else:
            cohort.enqueue_calculation(initiating_user=request.user)

        report_user_action(request.user, "cohort created", cohort.get_analytics_metadata())
        return cohort

    def _parse_csv_file(self, file) -> tuple[list[str], Iterator[list[str]]]:
        """Handle file reading and CSV parsing with error handling"""
        decoded_file = file.read().decode(CSVConfig.ENCODING).splitlines()
        reader = csv.reader(decoded_file)

        # Skip empty rows at the beginning
        first_row: list[str] = []
        while not first_row:
            row = next(reader, None)
            if row is None:
                raise ValidationError({"csv": [CSVConfig.ErrorMessages.EMPTY_FILE]})
            first_row = row

        return first_row, reader

    def _is_single_column_format(self, first_row: list) -> bool:
        """Determine if CSV should be treated as single-column format"""
        non_empty_cols = [col for col in first_row if col.strip()]
        return len(non_empty_cols) <= 1

    def _is_person_id_header(self, header: str) -> bool:
        """Check if header indicates person_id column"""
        person_id_headers_lower = [h.lower() for h in CSVConfig.PERSON_ID_HEADERS]
        return header.strip().lower() in person_id_headers_lower

    def _is_email_header(self, header: str) -> bool:
        """Check if header indicates email column"""
        email_headers_lower = [h.lower() for h in CSVConfig.EMAIL_HEADERS]
        return header.strip().lower() in email_headers_lower

    def _find_id_column(self, headers: list[str]) -> tuple[int, str] | None:
        """Find the index and type of the ID column in headers, with preference order: person_id > distinct_id > email"""
        normalized_headers = [h.strip() for h in headers]
        normalized_lower_headers = [h.lower() for h in normalized_headers]

        # First, look for person_id columns (preferred) - use case-insensitive matching
        person_id_headers_lower = [h.lower() for h in CSVConfig.PERSON_ID_HEADERS]
        for i, header in enumerate(normalized_lower_headers):
            if header in person_id_headers_lower:
                return i, "person_id"

        # Then, look for distinct_id columns
        for i, header in enumerate(normalized_lower_headers):
            if header in CSVConfig.DISTINCT_ID_HEADERS:
                return i, "distinct_id"

        # Finally, look for email columns
        email_headers_lower = [h.lower() for h in CSVConfig.EMAIL_HEADERS]
        for i, header in enumerate(normalized_lower_headers):
            if header in email_headers_lower:
                return i, "email"

        return None

    def _extract_ids_single_column(
        self, first_row: list[str], reader: Iterator[list[str]], skip_header: bool = False
    ) -> list[str]:
        """Process single-column CSV format"""
        distinct_ids = []

        # Include first row only if it's not a header
        if not skip_header and first_row and first_row[0].strip() != "":
            distinct_ids.append(first_row[0].strip())

        for row in reader:
            if len(row) > 0:
                stripped_id = row[0].strip()
                if stripped_id != "":
                    distinct_ids.append(stripped_id)
        return distinct_ids

    def _extract_ids_multi_column(self, reader: Iterator[list[str]], id_col: int, cohort_pk: int) -> list[str]:
        """Process multi-column CSV format with robust error handling"""
        ids = []
        skipped_rows = 0

        for row in reader:
            # Skip rows with incorrect number of columns
            if len(row) <= id_col:
                skipped_rows += 1
                continue

            # Extract ID if present and non-empty
            id_value = row[id_col].strip()
            if id_value != "":
                ids.append(id_value)

        if skipped_rows > 0:
            logger.info(f"Skipped {skipped_rows} rows with incorrect column count in CSV for cohort {cohort_pk}")

        return ids

    def _validate_and_process_ids(self, ids: list[str], id_type: str, cohort: Cohort) -> None:
        """Final validation and task scheduling"""
        from posthog.tasks.calculate_cohort import calculate_cohort_from_list

        if not ids:
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.NO_VALID_IDS]})

        logger.info(f"Processing CSV upload for cohort {cohort.pk} with {len(ids)} {id_type}s")
        calculate_cohort_from_list.delay(cohort.pk, ids, team_id=self.context["team_id"], id_type=id_type)

    def _handle_csv_errors(self, e: Exception, cohort: Cohort) -> None:
        """Centralized error handling with consistent exception capture"""

        # Reset calculating flag on error
        cohort.is_calculating = False
        cohort.save(update_fields=["is_calculating"])

        if isinstance(e, UnicodeDecodeError):
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.ENCODING_ERROR]})
        elif isinstance(e, csv.Error):
            capture_exception(e, additional_properties={"cohort_id": cohort.pk, "team_id": self.context["team_id"]})
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.FORMAT_ERROR]})
        elif isinstance(e, ValidationError):
            # If it's already a ValidationError, just re-raise it to preserve format
            raise
        else:
            capture_exception(e, additional_properties={"cohort_id": cohort.pk, "team_id": self.context["team_id"]})
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.GENERIC_ERROR]})

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        """Main orchestration method for CSV processing - clear high-level flow"""
        # Set calculating flag immediately so UI shows loading state
        cohort.is_calculating = True
        cohort.save(update_fields=["is_calculating"])

        try:
            first_row, reader = self._parse_csv_file(file)

            if self._is_single_column_format(first_row):
                # Check if single column header indicates person_id
                if first_row and self._is_person_id_header(first_row[0]):
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=True)
                    id_type = "person_id"
                # Check if single column header indicates email
                elif first_row and self._is_email_header(first_row[0]):
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=True)
                    id_type = "email"
                else:
                    # Single column format treated as distinct_ids for backwards compatibility
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=False)
                    id_type = "distinct_id"
            else:
                result = self._find_id_column(first_row)

                if result is None:
                    available_headers = [h for h in first_row if h.strip()]
                    raise ValidationError(
                        {
                            "csv": [
                                CSVConfig.ErrorMessages.MISSING_ID_COLUMN.format(
                                    columns=", ".join(available_headers) if available_headers else "none"
                                )
                            ]
                        }
                    )

                id_col, id_type = result
                ids = self._extract_ids_multi_column(reader, id_col, cohort.pk)

            self._validate_and_process_ids(ids, id_type, cohort)

        except Exception as e:
            self._handle_csv_errors(e, cohort)

    def validate_query(self, query: Optional[dict]) -> Optional[dict]:
        if not query:
            return None
        if not isinstance(query, dict):
            raise ValidationError("Query must be a dictionary.")
        if query.get("kind") == "ActorsQuery":
            ActorsQuery.model_validate(query)
        elif query.get("kind") == "HogQLQuery":
            HogQLQuery.model_validate(query)
        else:
            raise ValidationError(f"Query must be an ActorsQuery or HogQLQuery. Got: {query.get('kind')}")
        return query

    def validate_filters(self, raw: dict):
        """
        1. structural/schema check → pydantic
        2. domain rules (feature-flag gotchas) → bespoke fn
        """
        # Skip validation for static cohorts
        if self.initial_data.get("is_static") or getattr(self.instance, "is_static", False):
            return raw
        if not isinstance(raw, dict) or "properties" not in raw:
            raise ValidationError(
                {"detail": "Must contain a 'properties' key with type and values", "type": "validation_error"}
            )
        try:
            CohortFilters.model_validate(raw)  # raises if malformed
        except PydanticValidationError as exc:
            # pydantic → drf error shape
            raise ValidationError(detail=self._cohort_error_message(exc))

        self._validate_feature_flag_constraints(raw)  # keep your side-rules
        return raw

    @staticmethod
    def _cohort_error_message(exc: PydanticValidationError) -> str:
        """
        make pydantic's missing-field error read like the old
        'Missing required keys for <kind> filter: <field>' string.
        if we can't map it, fall back to the raw pydantic payload.
        """
        for err in exc.errors():
            # custom ValueError raised by model_validator
            if err["type"] == "value_error":
                msg = err["msg"]
                idx = msg.find("Missing required keys")
                if idx != -1:
                    return msg[idx:]  # strip the "Value error, " prefix

            # generic missing-field case
            if err["type"] == "missing":
                loc = [str(p) for p in err["loc"]]
                missing_field = loc[-1]
                for kind in ("behavioral", "cohort", "person"):
                    if kind in loc:
                        return f"Missing required keys for {kind} filter: {missing_field}"
        return str(exc.errors())

    def _validate_feature_flag_constraints(self, request_filters: dict):
        if self.context["request"].method != "PATCH":
            return

        parsed_filter = Filter(data=request_filters)
        instance = cast(Cohort, self.instance)
        cohort_id = instance.pk

        flags = FeatureFlag.objects.filter(team__project_id=self.context["project_id"], active=True, deleted=False)
        cohort_used_in_flags = len([flag for flag in flags if cohort_id in flag.get_cohort_ids()]) > 0

        if not cohort_used_in_flags:
            return

        for prop in parsed_filter.property_groups.flat:
            if prop.type == "behavioral":
                raise serializers.ValidationError(
                    detail="Behavioral filters cannot be added to cohorts used in feature flags.",
                    code="behavioral_cohort_found",
                )

            if prop.type == "cohort":
                self._validate_nested_cohort_behavioral_filters(prop, cohort_used_in_flags)

    def _validate_nested_cohort_behavioral_filters(self, prop: Any, cohort_used_in_flags: bool):
        nested_cohort = Cohort.objects.get(pk=prop.value, team__project_id=self.context["project_id"])
        dependency_cohorts = get_all_cohort_dependencies(nested_cohort)

        for dependency_cohort in [nested_cohort, *dependency_cohorts]:
            if cohort_used_in_flags and any(p.type == "behavioral" for p in dependency_cohort.properties.flat):
                raise serializers.ValidationError(
                    detail=f"A cohort dependency ({dependency_cohort.name}) has filters based on events. These cohorts can't be used in feature flags.",
                    code="behavioral_cohort_found",
                )

    def update(self, cohort: Cohort, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]

        cohort.name = validated_data.get("name", cohort.name)
        cohort.description = validated_data.get("description", cohort.description)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        cohort.filters = validated_data.get("filters", cohort.filters)
        cohort.cohort_type = validated_data.get("cohort_type", cohort.cohort_type)
        cohort.query = validated_data.get("query", cohort.query)

        deleted_state = validated_data.get("deleted", None)

        is_deletion_change = deleted_state is not None and cohort.deleted != deleted_state
        if is_deletion_change:
            if deleted_state:
                flags_using_cohort = FeatureFlag.objects.filter(
                    team__project_id=cohort.team.project_id, active=True, deleted=False
                )
                flags_with_cohort = [flag for flag in flags_using_cohort if cohort.id in flag.get_cohort_ids()]
                if flags_with_cohort:
                    flag_names = [flag.name or flag.key for flag in flags_with_cohort]
                    raise ValidationError(
                        f"This cohort is used in {len(flags_with_cohort)} active feature flag(s): {', '.join(flag_names)}. "
                        "Please remove the cohort from these feature flags before deleting it."
                    )

            relevant_team_ids = Team.objects.filter(project_id=cohort.team.project_id).values_list("id", flat=True)
            cohort.deleted = deleted_state
            if deleted_state:
                # De-attach from experiments
                cohort.experiment_set.set([])

                AsyncDeletion.objects.bulk_create(
                    [
                        AsyncDeletion(
                            deletion_type=DeletionType.Cohort_full,
                            team_id=team_id,
                            # Only appending `team_id` if it's not the same as the cohort's `team_id``, so that
                            # the migration to environments does not accidentally cause duplicate `AsyncDeletion`s
                            key=f"{cohort.pk}_{cohort.version}{('_' + str(team_id)) if team_id != cohort.team_id else ''}",
                        )
                        for team_id in relevant_team_ids
                    ],
                    ignore_conflicts=True,
                )
            else:
                AsyncDeletion.objects.filter(
                    deletion_type=DeletionType.Cohort_full,
                    key__startswith=f"{cohort.pk}_{cohort.version}",  # We target this _prefix_, so all teams are covered
                ).delete()
        elif not cohort.is_static:
            cohort.is_calculating = True

        if will_create_loops(cohort):
            raise ValidationError("Cohorts cannot reference other cohorts in a loop.")

        cohort.save()

        if not deleted_state:
            from posthog.tasks.calculate_cohort import insert_cohort_from_query

            if cohort.is_static and request.FILES.get("csv"):
                # You can't update a static cohort using the trend/stickiness thing
                self._calculate_static_by_csv(request.FILES["csv"], cohort)
            elif cohort.is_static and validated_data.get("query"):
                insert_cohort_from_query.delay(cohort.pk, self.context["team_id"])
            else:
                cohort.enqueue_calculation(initiating_user=request.user)

        report_user_action(
            request.user,
            "cohort updated",
            {
                **cohort.get_analytics_metadata(),
                "updated_by_creator": request.user == cohort.created_by,
            },
        )

        return cohort

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["filters"] = (
            instance.filters if instance.filters else {"properties": instance.properties.to_dict()}
        )
        return representation


class CohortViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    scope_object = "cohort"

    def _filter_request(self, request: Request, queryset: QuerySet) -> QuerySet:
        filters = request.GET.dict()

        for key in filters:
            if key == "type":
                cohort_type = filters[key]
                if cohort_type == "static":
                    queryset = queryset.filter(is_static=True)
                elif cohort_type == "dynamic":
                    queryset = queryset.filter(is_static=False)
            elif key == "created_by_id":
                queryset = queryset.filter(created_by_id=request.GET["created_by_id"])
            elif key == "search":
                queryset = queryset.filter(name__icontains=request.GET["search"])

        return queryset

    def safely_get_queryset(self, queryset) -> QuerySet:
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

            # TODO: remove this filter once we can support behavioral cohorts for feature flags, it's only
            # used in the feature flag property filter UI
            if self.request.query_params.get("hide_behavioral_cohorts", "false").lower() == "true":
                all_cohorts = {cohort.id: cohort for cohort in queryset.all()}
                behavioral_cohort_ids = self._find_behavioral_cohorts(all_cohorts)
                queryset = queryset.exclude(id__in=behavioral_cohort_ids)

            # add additional filters provided by the client
            queryset = self._filter_request(self.request, queryset)

        return queryset.prefetch_related("experiment_set", "created_by", "team").order_by("-created_at")

    def _find_behavioral_cohorts(self, all_cohorts: dict[int, Cohort]) -> set[int]:
        """
        Find all cohorts that have behavioral filters or reference cohorts with behavioral filters
        using a graph-based approach.
        """
        graph, behavioral_cohorts = self._build_cohort_dependency_graph(all_cohorts)
        affected_cohorts = set(behavioral_cohorts)

        def find_affected_cohorts() -> None:
            changed = True
            while changed:
                changed = False
                for source_id in list(graph.keys()):
                    if source_id not in affected_cohorts:
                        # NB: If this cohort points to any affected cohort, it's also affected
                        if any(target_id in affected_cohorts for target_id in graph[source_id]):
                            affected_cohorts.add(source_id)
                            changed = True

        find_affected_cohorts()
        return affected_cohorts

    def _build_cohort_dependency_graph(self, all_cohorts: dict[int, Cohort]) -> tuple[dict[int, set[int]], set[int]]:
        """
        Builds a directed graph of cohort dependencies and identifies behavioral cohorts.
        Returns (adjacency_list, behavioral_cohort_ids).
        """
        graph = defaultdict(set)
        behavioral_cohorts = set()

        def check_property_values(values: Any, source_id: int) -> None:
            """Process property values to build graph edges and identify behavioral cohorts."""
            if not isinstance(values, list):
                return

            for value in values:
                if not isinstance(value, dict):
                    continue

                if value.get("type") == "behavioral":
                    behavioral_cohorts.add(source_id)
                elif value.get("type") == "cohort":
                    try:
                        target_id = int(value.get("value", "0"))
                        if target_id in all_cohorts:
                            graph[source_id].add(target_id)
                    except ValueError:
                        continue
                elif value.get("type") in ("AND", "OR") and value.get("values"):
                    check_property_values(value["values"], source_id)

        for cohort_id, cohort in all_cohorts.items():
            if cohort.filters:
                properties = cohort.filters.get("properties", {})
                if isinstance(properties, dict):
                    check_property_values(properties.get("values", []), cohort_id)

        return graph, behavioral_cohorts

    @extend_schema(summary="Duplicate as static cohort", description="Create a static copy of a dynamic cohort")
    @action(methods=["GET"], detail=True, required_scopes=["cohort:write"])
    def duplicate_as_static_cohort(self, request: Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        team = self.team

        if cohort.is_static:
            raise ValidationError("Cannot duplicate a static cohort as a static cohort.")

        cohort_serializer = CohortSerializer(
            data={
                "name": f"{cohort.name} (static copy)",
                "is_static": True,
            },
            context={
                "request": request,
                "from_cohort_id": cohort.pk,
                "team_id": team.pk,
                "get_team": lambda: team,
            },
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort_serializer.save()

        return Response(cohort_serializer.data)

    @action(
        methods=["GET"],
        detail=True,
        renderer_classes=[
            *api_settings.DEFAULT_RENDERER_CLASSES,
            csvrenderers.PaginatedCSVRenderer,
        ],
        required_scopes=["cohort:read", "person:read"],
    )
    def persons(self, request: Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        team = self.team
        filter = Filter(request=request, team=self.team)
        assert request.user.is_authenticated

        is_csv_request = self.request.accepted_renderer.format == "csv" or request.GET.get("is_csv_export")
        if is_csv_request and not filter.limit:
            filter = filter.shallow_clone({LIMIT: CSV_EXPORT_LIMIT, OFFSET: 0})
        elif not filter.limit:
            filter = filter.shallow_clone({LIMIT: 100})

        query, params = PersonQuery(filter, team.pk, cohort=cohort).get_query(paginate=True)
        raw_result = sync_execute(
            query,
            {**params, **filter.hogql_context.values},
            # workload=Workload.OFFLINE,  # this endpoint is only used by external API requests
        )
        actor_ids = [row[0] for row in raw_result]
        serialized_actors = get_serialized_people(team, actor_ids, distinct_id_limit=10)

        _should_paginate = len(actor_ids) >= filter.limit

        next_url = format_query_params_absolute_url(request, filter.offset + filter.limit) if _should_paginate else None
        previous_url = (
            format_query_params_absolute_url(request, filter.offset - filter.limit)
            if filter.offset - filter.limit >= 0
            else None
        )
        if is_csv_request:
            KEYS_ORDER = [
                "id",
                "email",
                "name",
                "created_at",
                "properties",
                "distinct_ids",
            ]
            DELETE_KEYS = [
                "value_at_data_point",
                "uuid",
                "type",
                "is_identified",
                "matched_recordings",
            ]
            for actor in serialized_actors:
                if actor["properties"].get("email"):
                    actor["email"] = actor["properties"]["email"]  # type: ignore
                    del actor["properties"]["email"]
            serialized_actors = [
                {  # type: ignore
                    k: v
                    for k, v in sorted(
                        actor.items(),
                        key=lambda item: KEYS_ORDER.index(item[0]) if item[0] in KEYS_ORDER else 999999,
                    )
                    if k not in DELETE_KEYS
                }
                for actor in serialized_actors
            ]

        # TEMPORARY: Work out usage patterns of this endpoint
        renderer = SafeJSONRenderer()
        size = len(renderer.render(serialized_actors))
        API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER.labels(team_id=team.pk).inc(size)

        return Response({"results": serialized_actors, "next": next_url, "previous": previous_url})

    @extend_schema(request=AddPersonsToStaticCohortRequestSerializer)
    @action(methods=["PATCH"], detail=True, required_scopes=["cohort:write"])
    def add_persons_to_static_cohort(self, request: request.Request, **kwargs):
        cohort: Cohort = self.get_object()
        if not cohort.is_static:
            raise ValidationError("Can only add users to static cohorts")
        person_ids = request.data.get("person_ids", None)
        if not isinstance(person_ids, list):
            raise ValidationError("person_ids must be a list")
        if len(person_ids) == 0:
            raise ValidationError("person_ids cannot be empty")
        if len(person_ids) > DEFAULT_COHORT_INSERT_BATCH_SIZE:
            raise ValidationError("List size exceeds limit")
        uuids = [
            str(uuid)
            for uuid in Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=self.team_id, uuid__in=person_ids)
            .values_list("uuid", flat=True)
        ]
        if len(uuids) == 0:
            raise ValidationError("No valid users to add to cohort")
        cohort.insert_users_list_by_uuid(uuids, team_id=self.team_id)
        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated_session(request),
            item_id=str(cohort.id),
            scope="Cohort",
            activity="persons_added_manually",
            detail=Detail(changes=[Change(type="Cohort", action="changed")]),
        )
        return Response({"success": True}, status=200)

    @extend_schema(request=RemovePersonRequestSerializer)
    @action(methods=["PATCH"], detail=True, required_scopes=["cohort:write"])
    def remove_person_from_static_cohort(self, request: request.Request, **kwargs):
        cohort: Cohort = self.get_object()
        if not cohort.is_static:
            raise ValidationError("Can only remove users from static cohorts")
        person_id = request.data.get("person_id", None)
        if not person_id:
            raise ValidationError("person_id is required")
        if not isinstance(person_id, str):
            raise ValidationError("person_id must be a string")

        # Validate UUID format
        try:
            uuid.UUID(person_id)
        except ValueError:
            raise ValidationError("person_id must be a valid UUID")

        # Check if person exists and belongs to this team
        try:
            person_uuid = Person.objects.db_manager(READ_DB_FOR_PERSONS).get(team_id=self.team_id, uuid=person_id).uuid
        except Person.DoesNotExist:
            raise NotFound("Person with this UUID does not exist in the cohort's team")

        success = cohort.remove_user_by_uuid(str(person_uuid), team_id=self.team_id)

        if not success:
            raise NotFound("Person is not part of the cohort")

        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated_session(request),
            item_id=str(cohort.id),
            scope="Cohort",
            activity="person_removed_manually",
            detail=Detail(changes=[Change(type="Cohort", action="changed")]),
        )
        return Response({"success": True}, status=200)

    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="Cohort", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not Cohort.objects.filter(id=item_id, team__project_id=self.project_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="Cohort",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["cohort:read"])
    def calculation_history(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "100"))
        offset = int(request.query_params.get("offset", "0"))

        cohort: Cohort = self.get_object()

        calculation_history = CohortCalculationHistory.objects.filter(cohort=cohort, team=self.team).order_by(
            "-started_at"
        )[offset : offset + limit]

        total_count = CohortCalculationHistory.objects.filter(cohort=cohort, team=self.team).count()

        serializer = CohortCalculationHistorySerializer(calculation_history, many=True)

        return Response(
            {
                "results": serializer.data,
                "count": total_count,
                "next": None if offset + limit >= total_count else f"?limit={limit}&offset={offset + limit}",
                "previous": None if offset == 0 else f"?limit={limit}&offset={max(0, offset - limit)}",
            }
        )

    def perform_create(self, serializer):
        serializer.save()
        instance = cast(Cohort, serializer.instance)

        # Although there are no changes when creating a Cohort, we synthesize one here because
        # it is helpful to show the list of people in the cohort when looking at the activity log.
        people = instance.to_dict()["people"]
        changes = dict_changes_between(
            "Cohort", previous={"people": []}, new={"people": people}, use_field_exclusions=True
        )

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance.id,
            scope="Cohort",
            activity="created",
            detail=Detail(changes=changes, name=instance.name),
        )

    def perform_update(self, serializer):
        instance = cast(Cohort, serializer.instance)
        instance_id = instance.id

        try:
            # Using to_dict() here serializer.save() was changing the instance in memory,
            # so we need to get the before state in a "detached" manner that won't be
            # affected by the serializer.save() call.
            before_update = Cohort.objects.get(pk=instance_id).to_dict()
        except Cohort.DoesNotExist:
            before_update = {}

        serializer.save()

        changes = dict_changes_between("Cohort", previous=before_update, new=instance.to_dict())

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated_session(serializer.context["request"]),
            item_id=instance_id,
            scope="Cohort",
            activity="updated",
            detail=Detail(changes=changes, name=instance.name),
        )


class LegacyCohortViewSet(CohortViewSet):
    param_derived_from_user_current_team = "team_id"


def will_create_loops(cohort: Cohort) -> bool:
    # Loops can only be formed when trying to update a Cohort, not when creating one
    project_id = cohort.team.project_id

    # We can model this as a directed graph, where each node is a Cohort and each edge is a reference to another Cohort
    # There's a loop only if there's a cycle in the directed graph. The "directed" bit is important.
    # For example, if Cohort A exists, and Cohort B references Cohort A, and Cohort C references both Cohort A & B
    # then, there's no cycle, because we can compute cohort A, using which we can compute cohort B, using which we can compute cohort C.

    # However, if cohort A depended on Cohort C, then we'd have a cycle, because we can't compute Cohort A without computing Cohort C, and on & on.

    # For a good explainer of this algorithm, see: https://www.geeksforgeeks.org/detect-cycle-in-a-graph/

    def dfs_loop_helper(current_cohort: Cohort, seen_cohorts, cohorts_on_path):
        seen_cohorts.add(current_cohort.pk)
        cohorts_on_path.add(current_cohort.pk)

        for property in current_cohort.properties.flat:
            if property.type == "cohort":
                if property.value in cohorts_on_path:
                    return True
                elif property.value not in seen_cohorts:
                    try:
                        nested_cohort = Cohort.objects.get(pk=property.value, team__project_id=project_id)
                    except Cohort.DoesNotExist:
                        raise ValidationError("Invalid Cohort ID in filter")

                    if dfs_loop_helper(nested_cohort, seen_cohorts, cohorts_on_path):
                        return True

        cohorts_on_path.remove(current_cohort.pk)
        return False

    return dfs_loop_helper(cohort, set(), set())


def insert_cohort_people_into_pg(cohort: Cohort, *, team_id: int):
    ids = sync_execute(
        f"SELECT person_id FROM {PERSON_STATIC_COHORT_TABLE} where team_id = %(team_id)s AND cohort_id = %(cohort_id)s",
        {"cohort_id": cohort.pk, "team_id": team_id},
    )
    cohort.insert_users_list_by_uuid_into_pg_only(items=[str(id[0]) for id in ids], team_id=team_id)


def insert_cohort_query_actors_into_ch(cohort: Cohort, *, team: Team):
    context = HogQLContext(enable_select_queries=True, team_id=team.id)
    query = print_cohort_hogql_query(cohort, context, team=team)
    insert_actors_into_cohort_by_query(cohort, query, {}, context, team_id=team.id)


def insert_cohort_actors_into_ch(cohort: Cohort, filter_data: dict, *, team_id: int):
    from_existing_cohort_id = filter_data.get("from_cohort_id")
    context: HogQLContext

    if from_existing_cohort_id:
        existing_cohort = Cohort.objects.get(pk=from_existing_cohort_id)
        query = """
            SELECT DISTINCT person_id as actor_id
            FROM cohortpeople
            WHERE team_id = %(team_id)s AND cohort_id = %(from_cohort_id)s AND version = %(version)s
            ORDER BY person_id
        """
        params = {
            "team_id": team_id,
            "from_cohort_id": existing_cohort.pk,
            "version": existing_cohort.version,
        }
        context = Filter(data=filter_data, team=cohort.team).hogql_context
    else:
        insight_type = filter_data.get("insight")
        query_builder: ActorBaseQuery

        if insight_type == INSIGHT_TRENDS:
            filter = Filter(data=filter_data, team=cohort.team)
            entity = get_target_entity(filter)
            query_builder = TrendsActors(cohort.team, entity, filter)
            context = filter.hogql_context
        elif insight_type == INSIGHT_STICKINESS:
            stickiness_filter = StickinessFilter(data=filter_data, team=cohort.team)
            entity = get_target_entity(stickiness_filter)
            query_builder = StickinessActors(cohort.team, entity, stickiness_filter)
            context = stickiness_filter.hogql_context
        elif insight_type == INSIGHT_FUNNELS:
            funnel_filter = Filter(data=filter_data, team=cohort.team)
            funnel_actor_class = get_funnel_actor_class(funnel_filter)
            query_builder = funnel_actor_class(filter=funnel_filter, team=cohort.team)
            context = funnel_filter.hogql_context
        elif insight_type == INSIGHT_LIFECYCLE:
            lifecycle_filter = LifecycleFilter(data=filter_data, team=cohort.team)
            query_builder = LifecycleActors(team=cohort.team, filter=lifecycle_filter)
            context = lifecycle_filter.hogql_context

        else:
            if settings.DEBUG:
                raise ValueError(f"Insight type: {insight_type} not supported for cohort creation")
            else:
                capture_exception(Exception(f"Insight type: {insight_type} not supported for cohort creation"))

        if query_builder.is_aggregating_by_groups:
            if settings.DEBUG:
                raise ValueError(f"Query type: Group based queries are not supported for cohort creation")
            else:
                capture_exception(Exception(f"Query type: Group based queries are not supported for cohort creation"))
        else:
            query, params = query_builder.actor_query(limit_actors=False)

    insert_actors_into_cohort_by_query(cohort, query, params, context, team_id=team_id)


def insert_actors_into_cohort_by_query(
    cohort: Cohort, query: str, params: dict[str, Any], context: HogQLContext, *, team_id: int
):
    sync_execute(
        INSERT_COHORT_ALL_PEOPLE_THROUGH_PERSON_ID.format(cohort_table=PERSON_STATIC_COHORT_TABLE, query=query),
        {
            "cohort_id": cohort.pk,
            "_timestamp": datetime.now(),
            "team_id": team_id,
            **context.values,
            **params,
        },
    )


def get_cohort_actors_for_feature_flag(cohort_id: int, flag: str, team_id: int, batchsize: int = 1_000):
    # :TODO: Find a way to incorporate this into the same code path as feature flag evaluation
    project_id = Team.objects.only("project_id").get(pk=team_id).project_id
    try:
        feature_flag = FeatureFlag.objects.get(team__project_id=project_id, key=flag)
    except FeatureFlag.DoesNotExist:
        return []

    if not feature_flag.active or feature_flag.deleted or feature_flag.aggregation_group_type_index is not None:
        return []

    cohort = Cohort.objects.get(pk=cohort_id, team__project_id=project_id)
    matcher_cache = FlagsMatcherCache(project_id=project_id)
    uuids_to_add_to_cohort = []
    cohorts_cache: dict[int, CohortOrEmpty] = {}

    if feature_flag.uses_cohorts:
        # TODO: Consider disabling flags with cohorts for creating static cohorts
        # because this is currently a lot more inefficient for flag matching,
        # as we're required to go to the database for each person.
        cohorts_cache = {
            cohort.pk: cohort for cohort in Cohort.objects.filter(team__project_id=project_id, deleted=False)
        }

    default_person_properties = {}
    for condition in feature_flag.conditions:
        property_list = Filter(data=condition).property_groups.flat
        for property in property_list:
            default_person_properties.update(get_default_person_property(property, cohorts_cache))

    flag_property_conditions = [Filter(data=condition).property_groups for condition in feature_flag.conditions]
    flag_property_group = PropertyGroup(type=PropertyOperatorType.OR, values=flag_property_conditions)

    try:
        # QuerySet.Iterator() doesn't work with pgbouncer, it will load everything into memory and then stream
        # which doesn't work for us, so need a manual chunking here.
        # Because of this pgbouncer transaction pooling mode, we can't use server-side cursors.
        # We pre-filter all persons to be ones that will match the feature flag, so that we don't have to
        # iterate through all persons
        queryset = (
            Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id)
            .filter(property_group_to_Q(team_id, flag_property_group, cohorts_cache=cohorts_cache))
            .order_by("id")
        )
        # get batchsize number of people at a time
        start = 0
        batch_of_persons = queryset[start : start + batchsize]
        while batch_of_persons:
            # TODO: Check if this subquery bulk fetch limiting is better than just doing a join for all distinct ids
            # OR, if row by row getting single distinct id is better
            # distinct_id = PersonDistinctId.objects.filter(person=person, team_id=team_id).values_list(
            #     "distinct_id", flat=True
            # )[0]
            distinct_id_subquery = Subquery(
                PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
                .filter(person_id=OuterRef("person_id"))
                .values_list("id", flat=True)[:3]
            )
            prefetch_related_objects(
                batch_of_persons,
                Prefetch(
                    "persondistinctid_set",
                    to_attr="distinct_ids_cache",
                    queryset=PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(
                        id__in=distinct_id_subquery
                    ),
                ),
            )

            all_persons = list(batch_of_persons)
            if len(all_persons) == 0:
                break

            for person in all_persons:
                # ignore almost-deleted persons / persons with no distinct ids
                if len(person.distinct_ids) == 0:
                    continue

                distinct_id = person.distinct_ids[0]
                person_overrides = {}
                if feature_flag.ensure_experience_continuity:
                    # :TRICKY: This is inefficient because it tries to get the hashkey overrides one by one.
                    # But reusing functions is better for maintainability. Revisit optimising if this becomes a bottleneck.
                    person_overrides = get_feature_flag_hash_key_overrides(
                        team_id, [distinct_id], person_id_to_distinct_id_mapping={person.id: distinct_id}
                    )

                try:
                    match = FeatureFlagMatcher(
                        team_id,
                        project_id,
                        [feature_flag],
                        distinct_id,
                        groups={},
                        cache=matcher_cache,
                        hash_key_overrides=person_overrides,
                        property_value_overrides={**default_person_properties, **person.properties},
                        group_property_value_overrides={},
                        cohorts_cache=cohorts_cache,
                    ).get_match(feature_flag)
                    if match.match:
                        uuids_to_add_to_cohort.append(str(person.uuid))
                except (DatabaseError, ValueError, ValidationError):
                    logger.exception(
                        "Error evaluating feature flag for person", person_uuid=str(person.uuid), team_id=team_id
                    )
                except Exception as err:
                    # matching errors are not fatal, so we just log them and move on.
                    # Capturing error for now just in case there are some unexpected errors
                    # we did not account for.
                    capture_exception(err)

                if len(uuids_to_add_to_cohort) >= batchsize:
                    cohort.insert_users_list_by_uuid(uuids_to_add_to_cohort, batchsize=batchsize, team_id=team_id)
                    uuids_to_add_to_cohort = []

            start += batchsize
            batch_of_persons = queryset[start : start + batchsize]

        if len(uuids_to_add_to_cohort) > 0:
            cohort.insert_users_list_by_uuid(uuids_to_add_to_cohort, batchsize=batchsize, team_id=team_id)

    except Exception as err:
        if settings.DEBUG or settings.TEST:
            raise
        capture_exception(err)


def get_default_person_property(prop: Property, cohorts_cache: dict[int, CohortOrEmpty]):
    default_person_properties = {}

    if prop.operator not in ("is_set", "is_not_set") and prop.type == "person":
        default_person_properties[prop.key] = ""
    elif prop.type == "cohort" and not isinstance(prop.value, list):
        try:
            parsed_cohort_id = int(prop.value)
        except (ValueError, TypeError):
            return None
        cohort = cohorts_cache.get(parsed_cohort_id)
        if cohort:
            return get_default_person_properties_for_cohort(cohort, cohorts_cache)
    return default_person_properties


def get_default_person_properties_for_cohort(cohort: Cohort, cohorts_cache: dict[int, CohortOrEmpty]) -> dict[str, str]:
    """
    Returns a dictionary of default person properties to use when evaluating a feature flag
    """
    default_person_properties = {}
    for property in cohort.properties.flat:
        default_person_properties.update(get_default_person_property(property, cohorts_cache))

    return default_person_properties
