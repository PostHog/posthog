import csv
import json
import time
import uuid
import hashlib
from collections.abc import Iterator
from copy import deepcopy
from typing import Annotated, Any, ClassVar, Literal, Optional, Union, cast

from django.db.models import OuterRef, QuerySet, Subquery
from django.utils import timezone

import requests
import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from prometheus_client import Counter, Histogram
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

from posthog.schema import ActorsQuery, HogQLQuery, ProductKey

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.constants import CSV_EXPORT_LIMIT
from posthog.hogql.property import PERSON_METADATA_FIELDS, property_to_expr

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.flags_service import FlagVersionConflictError, batch_evaluate_flag_for_team
from posthog.api.shared import SearchMatchTypeSerializerMixin, UserBasicSerializer
from posthog.api.utils import action
from posthog.cdp.filters import build_behavioral_event_expr
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.constants import LIMIT, OFFSET
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.helpers.trigram_search import MAX_SEARCH_LENGTH, NAME_FIELD, apply_trigram_search, normalize_search_term
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import User
from posthog.models.activity_logging.activity_log import (
    Change,
    Detail,
    dict_changes_between,
    load_activity,
    log_activity,
)
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.filters.filter import Filter
from posthog.models.filters.utils import earliest_timestamp_func
from posthog.models.person.util import get_person_by_uuid, validate_person_uuids_exist
from posthog.models.property.property import Property
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT
from posthog.personhog_client.caller_tag import personhog_caller_tag
from posthog.queries.actor_base_query import get_serialized_people
from posthog.queries.base import determine_parsed_date_for_property_matching
from posthog.renderers import SafeJSONRenderer
from posthog.utils import format_query_params_absolute_url, str_to_bool

from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import (
    DEFAULT_COHORT_INSERT_BATCH_SIZE,
    REALTIME_COHORT_MAX_PERSON_COUNT,
    Cohort,
    CohortOrEmpty,
    CohortType,
)
from products.cohorts.backend.models.dependencies import get_flag_excluded_behavioral_cohort_ids
from products.cohorts.backend.models.util import (
    CohortErrorCode,
    cohort_filters_have_values,
    get_all_cohort_dependencies,
    get_friendly_error_message,
)
from products.cohorts.backend.models.validation import CohortTypeValidationSerializer
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.product_analytics.backend.models.insight import Insight


# Mirrors SerializedPerson in posthog/queries/actor_base_query.py.
# Nullability mirrors the TypedDict: only Optional[...] fields are nullable; matched_recordings
# and value_at_data_point are always present in the response (always-set keys), even if empty/None.
class CohortPersonResultSerializer(serializers.Serializer):
    id = serializers.CharField()
    uuid = serializers.UUIDField()
    type = serializers.ChoiceField(choices=["person"])
    name = serializers.CharField()
    distinct_ids = serializers.ListField(child=serializers.CharField())
    properties = serializers.DictField()
    created_at = serializers.DateTimeField(allow_null=True)
    last_seen_at = serializers.DateTimeField(allow_null=True)
    is_identified = serializers.BooleanField(allow_null=True)
    matched_recordings = serializers.ListField(child=serializers.DictField())
    value_at_data_point = serializers.FloatField(allow_null=True)


class CohortPersonsResponseSerializer(serializers.Serializer):
    results = CohortPersonResultSerializer(many=True)
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)


def validate_filters_and_compute_realtime_support(
    filters_dict: dict,
    team: Team,
    current_cohort_type: str | None = None,
    cohort_count: int | None = None,
) -> tuple[dict, str | None, list[str] | None]:
    try:
        if not filters_dict:
            return filters_dict, current_cohort_type, None

        # Defensive check: ensure properties exists and has required structure
        if "properties" not in filters_dict:
            error_msg = "Cohort filter missing properties key"
            logger.warning(error_msg)
            return filters_dict, current_cohort_type, [error_msg]

        properties = filters_dict["properties"]
        if not isinstance(properties, dict):
            error_msg = "Cohort filter properties is not a dict"
            logger.warning(error_msg)
            return filters_dict, current_cohort_type, [error_msg]

        # Check if properties is empty or missing required fields
        if not properties or ("type" not in properties and "values" not in properties):
            error_msg = "Cohort filter properties missing type or values"
            logger.warning(error_msg)
            return filters_dict, current_cohort_type, [error_msg]

        validated_filters = CohortFilters.model_validate({"properties": properties}, context={"team": team})

        clean_filters = validated_filters.model_dump(exclude_none=True)

        cohort_type = (
            CohortType.REALTIME
            if _calculate_realtime_support(cast(CohortFilterGroup, validated_filters.properties))
            else None
        )

        # Check if cohort exceeds the maximum person count for real-time evaluation
        if cohort_type == CohortType.REALTIME and cohort_count is not None:
            if cohort_count > REALTIME_COHORT_MAX_PERSON_COUNT:
                cohort_type = None

        return clean_filters, cohort_type, None

    except Exception as e:
        logger.warning(f"Failed to validate cohort filters: {e}")
        return filters_dict, current_cohort_type, [str(e)]


def generate_cohort_filter_bytecode(filter_data: dict, team: Team) -> tuple[list[Any] | None, str | None, str | None]:
    """
    Generate HogQL bytecode for cohort filter data.
    Similar to generate_template_bytecode in validation.py but for cohort-specific filters.
    Returns tuple of (bytecode, error, conditionHash)
    """
    try:
        # Only treat behavioral as event matcher + optional event properties; unsupported values return None
        if filter_data.get("type") == "behavioral":
            expr = build_behavioral_event_expr(filter_data, team)
            # Unsupported behavioral filters return None → skip bytecode
            if expr is None:
                return None, "Unsupported behavioral filter for realtime bytecode", None
            bytecode = create_bytecode(expr, cohort_membership_supported=True, null_safe_comparisons=True).bytecode
            condition_hash = None
            if bytecode:
                bytecode_str = json.dumps(bytecode, sort_keys=True)
                condition_hash = hashlib.sha256(bytecode_str.encode()).hexdigest()[:16]
            return bytecode, None, condition_hash

        # Check if it's a cohort filter referencing another cohort
        if filter_data.get("type") == "cohort":
            cohort_id = filter_data.get("value")
            if cohort_id is None:
                # If cohort_id is missing, don't generate bytecode
                return None, None, None
            # Type narrowing: cohort_id is not None at this point, and should be int
            try:
                cohort_id_int = int(cohort_id)
            except (ValueError, TypeError):
                return None, None, None
            try:
                referenced_cohort = Cohort.objects.get(team__project_id=team.project_id, id=cohort_id_int)
                # Check if the referenced cohort is realtime
                if referenced_cohort.cohort_type != CohortType.REALTIME:
                    # Don't generate bytecode for non-realtime cohort references
                    return None, None, None
            except Cohort.DoesNotExist:
                # If cohort doesn't exist, don't generate bytecode
                return None, None, None

        property_obj = Property(**filter_data)
        expr = property_to_expr(property_obj, team)
        bytecode = create_bytecode(expr, cohort_membership_supported=True, null_safe_comparisons=True).bytecode

        # Generate conditionHash from bytecode
        condition_hash = None
        if bytecode:
            # Create a stable hash of the bytecode by converting to JSON string
            bytecode_str = json.dumps(bytecode, sort_keys=True)
            condition_hash = hashlib.sha256(bytecode_str.encode()).hexdigest()[:16]

        return bytecode, None, condition_hash
    except Exception as e:
        logger.warning(f"Failed to generate bytecode for cohort filter: {e}")
        return None, str(e), None


class FilterBytecodeMixin(BaseModel):
    bytecode: list[Any] | None = None
    bytecode_error: str | None = None
    conditionHash: str | None = None

    @model_validator(mode="after")
    def _generate_bytecode(self, info):
        """Generate bytecode for the filter if team context is available."""
        if info and info.context:
            team = info.context.get("team")
            if team:
                bytecode, error, condition_hash = generate_cohort_filter_bytecode(
                    self.model_dump(exclude_none=True), team
                )
                if bytecode:
                    self.bytecode = bytecode
                if condition_hash:
                    self.conditionHash = condition_hash
                if error:
                    self.bytecode_error = error
        return self


class EventPropFilter(BaseModel, extra="forbid"):
    type: Literal["event", "element"]
    key: str
    value: Any
    operator: str | None = None


class HogQLFilter(BaseModel, extra="forbid"):
    type: Literal["hogql"]
    key: str
    value: Any | None = None


class BehavioralFilter(FilterBytecodeMixin, BaseModel, extra="forbid"):
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
    explicit_datetime_to: str | None = None


class CohortFilter(FilterBytecodeMixin, BaseModel, extra="forbid"):
    type: Literal["cohort"]
    key: Literal["id"]
    value: int
    negation: bool = False


# Date operators that require date value validation
# Note: is_date_exact is not yet supported (see posthog/models/property/util.py)
# Keep in sync with OperatorType in posthog/models/property/property.py
DATE_OPERATORS = ("is_date_after", "is_date_before")


class PersonValueValidationMixin(BaseModel):
    """Shared value/operator presence and date-value validation for the person and
    person_metadata filter variants. `_filter_noun` names the variant in error messages."""

    _filter_noun: ClassVar[str]

    operator: str | None = None  # accept any legacy operator
    value: Any | None = None  # mostly likely it's list[str], str, or None

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
            raise ValueError(f"Missing required keys for {self._filter_noun} filter: {', '.join(missing)}")

        return self

    @model_validator(mode="after")
    def _validate_date_value(self):
        if self.operator in DATE_OPERATORS and self.value is not None:
            parsed_date = determine_parsed_date_for_property_matching(self.value)
            if not parsed_date:
                raise ValueError(
                    f"Invalid date value '{self.value}' for operator '{self.operator}'. "
                    f"Expected a relative date (e.g., '-7d', '30d') or an ISO 8601 date (e.g., '2024-01-15')."
                )

        return self


class PersonFilter(FilterBytecodeMixin, PersonValueValidationMixin, extra="forbid"):
    _filter_noun: ClassVar[str] = "person"

    type: Literal["person"]
    key: str
    negation: bool = False


class PersonMetadataFilter(FilterBytecodeMixin, PersonValueValidationMixin, extra="forbid"):
    """Filter on a top-level persons-table column (e.g. created_at) rather than the
    properties JSON. The matching key must be one of PERSON_METADATA_FIELDS."""

    _filter_noun: ClassVar[str] = "person_metadata"

    type: Literal["person_metadata"]
    key: str
    negation: bool = False

    @model_validator(mode="after")
    def _validate_key(self):
        if self.key not in PERSON_METADATA_FIELDS:
            allowed = ", ".join(sorted(PERSON_METADATA_FIELDS))
            raise ValueError(f"Unsupported person_metadata key '{self.key}'. Allowed keys: {allowed}.")
        return self


PropertyFilter = Annotated[
    Union[BehavioralFilter, CohortFilter, PersonFilter, PersonMetadataFilter],
    Field(discriminator="type"),
]

FilterOrGroup = Annotated[Union[PropertyFilter, "CohortFilterGroup"], Field(discriminator="type")]


class CohortFilterGroup(BaseModel, extra="forbid"):
    """AND/OR group containing cohort filters. Named to avoid collision with analytics Group model."""

    type: Literal["AND", "OR"]
    values: list[FilterOrGroup]


CohortFilterGroup.model_rebuild()


def _calculate_realtime_support(group: CohortFilterGroup) -> bool:
    """Check if all filters in the group have valid bytecode to determine realtime support."""
    for value in group.values:
        if hasattr(value, "values"):  # It's another group
            if not _calculate_realtime_support(cast(CohortFilterGroup, value)):
                return False
        else:  # It's a filter
            # person_metadata reads top-level persons-table columns, which the realtime
            # precalculated_person_properties table doesn't carry. Any cohort referencing one
            # must use the standard (non-realtime) calculation path, so force the whole cohort
            # non-realtime as soon as a person_metadata filter appears in any group.
            if getattr(value, "type", None) == "person_metadata":
                return False
            # Check if filter has FilterBytecodeMixin and valid bytecode
            if hasattr(value, "bytecode") and hasattr(value, "bytecode_error"):
                if value.bytecode is None or value.bytecode_error is not None:
                    return False
            else:
                # Filter doesn't support bytecode generation
                return False
    return True


class CohortFilters(BaseModel, extra="forbid"):
    properties: CohortFilterGroup


API_COHORT_PERSON_BYTES_READ_FROM_POSTGRES_COUNTER = Counter(
    "api_cohort_person_bytes_read_from_postgres",
    "An estimate of how many bytes we've read from postgres to service person cohort endpoint.",
    labelnames=[LABEL_TEAM_ID],
)

logger = structlog.get_logger(__name__)


class AddPersonsToStaticCohortRequestSerializer(serializers.Serializer):
    person_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        help_text="List of person UUIDs to add to the cohort",
    )


class RemovePersonRequestSerializer(serializers.Serializer):
    person_id = serializers.UUIDField(required=True, help_text="Person UUID to remove from the cohort")


COHORT_USED_IN_PAGE_SIZE = 100


class CohortUsedInFlagSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Feature flag database ID")
    key = serializers.CharField(help_text="Feature flag key (URL slug)")
    name = serializers.CharField(allow_null=True, allow_blank=True, help_text="Feature flag display name")


class CohortUsedInInsightSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Insight database ID")
    short_id = serializers.CharField(help_text="Insight short ID used for routing in the frontend")
    name = serializers.CharField(
        help_text="Insight display name; falls back to derived name, then to 'Unnamed' when both are empty"
    )


class CohortUsedInCohortSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Cohort database ID")
    name = serializers.CharField(help_text="Cohort display name; falls back to 'Unnamed' when empty")


class CohortUsedInFlagsBlockSerializer(serializers.Serializer):
    results = CohortUsedInFlagSerializer(
        many=True, help_text=f"Feature flags referencing this cohort, capped at {COHORT_USED_IN_PAGE_SIZE} results"
    )
    total = serializers.IntegerField(
        help_text="Total number of feature flags referencing this cohort, before truncation"
    )
    has_more = serializers.BooleanField(help_text="True when more feature flags exist beyond the truncation cap")


class CohortUsedInInsightsBlockSerializer(serializers.Serializer):
    results = CohortUsedInInsightSerializer(
        many=True, help_text=f"Insights referencing this cohort, capped at {COHORT_USED_IN_PAGE_SIZE} results"
    )
    total = serializers.IntegerField(help_text="Total number of insights referencing this cohort, before truncation")
    has_more = serializers.BooleanField(help_text="True when more insights exist beyond the truncation cap")


class CohortUsedInCohortsBlockSerializer(serializers.Serializer):
    results = CohortUsedInCohortSerializer(
        many=True,
        help_text=f"Cohorts that include this cohort as a criterion, capped at {COHORT_USED_IN_PAGE_SIZE} results",
    )
    total = serializers.IntegerField(help_text="Total number of cohorts referencing this cohort, before truncation")
    has_more = serializers.BooleanField(help_text="True when more cohorts exist beyond the truncation cap")


class CohortUsedInResponseSerializer(serializers.Serializer):
    feature_flags = CohortUsedInFlagsBlockSerializer(
        help_text="Feature flags (active and inactive, excluding soft-deleted) that reference this cohort in their targeting conditions, with truncation metadata",
    )
    insights = CohortUsedInInsightsBlockSerializer(
        help_text="Insights referencing this cohort with truncation metadata"
    )
    cohorts = CohortUsedInCohortsBlockSerializer(
        help_text="Other cohorts that include this cohort as a criterion, with truncation metadata"
    )


class CohortCalculationHistorySerializer(serializers.ModelSerializer):
    duration_seconds = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()
    is_successful = serializers.ReadOnlyField()
    total_query_ms = serializers.ReadOnlyField()
    total_memory_mb = serializers.ReadOnlyField()
    total_read_rows = serializers.ReadOnlyField()
    total_written_rows = serializers.ReadOnlyField()
    main_query = serializers.ReadOnlyField()
    main_query_id = serializers.ReadOnlyField()

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
            "main_query_id",
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


class CohortMinimalSerializer(serializers.ModelSerializer):
    """Minimal serializer for cohort references (e.g., person cohorts endpoint)."""

    class Meta:
        model = Cohort
        fields = ["id", "name", "count"]


@extend_schema_field(CohortFilters)  # type: ignore[arg-type]
class CohortFiltersField(serializers.JSONField):
    """Custom JSONField that exposes proper OpenAPI schema for cohort filters."""

    pass


class CohortSerializer(SearchMatchTypeSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    earliest_timestamp_func = earliest_timestamp_func
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    _create_static_person_ids = serializers.ListField(
        required=False, child=serializers.CharField(), write_only=True, default=[]
    )

    # Explicit filters field with proper OpenAPI schema
    filters = CohortFiltersField(required=False, allow_null=True)

    # If this cohort is an exposure cohort for an experiment
    experiment_set: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(many=True, read_only=True)  # ty: ignore[invalid-assignment]
    last_error_message = serializers.SerializerMethodField()

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
            "version",
            "pending_version",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "last_backfill_person_properties_at",
            "errors_calculating",
            "last_error_message",
            "count",
            "is_static",
            "cohort_type",
            "experiment_set",
            "search_match_type",
            "_create_in_folder",
            "_create_static_person_ids",
        ]
        read_only_fields = [
            "id",
            "version",
            "pending_version",
            "is_calculating",
            "created_by",
            "created_at",
            "last_calculation",
            "last_backfill_person_properties_at",
            "errors_calculating",
            "last_error_message",
            "count",
            "experiment_set",
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Basic list payload (opt-in via `?basic=true` on the list endpoint): drop
        # the heavy JSON columns the cohort picker never reads. Keeps the
        # response small for teams with thousands of cohorts. Default output is
        # unchanged; only callers that explicitly ask get the trimmed shape.
        if self.context.get("basic_cohort_list"):
            for field_name in ("filters", "query", "groups"):
                self.fields.pop(field_name, None)

    def get_last_error_message(self, cohort: Cohort) -> Optional[str]:
        # Prefer the annotated last_error_code when available
        if hasattr(cohort, "last_error_code"):
            if cohort.last_error_code:
                return get_friendly_error_message(cohort.last_error_code)
            return None

        # Fall back to querying calculation history.
        # Old records may have error set but error_code=NULL; get_friendly_error_message
        # returns None for those, so they won't surface user-facing messages.
        last_failed_calculation = (
            CohortCalculationHistory.objects.filter(cohort=cohort)
            .exclude(error__isnull=True)
            .exclude(error="")
            .order_by("-started_at")
            .first()
        )
        if last_failed_calculation:
            return get_friendly_error_message(last_failed_calculation.error_code)
        return None

    def validate_cohort_type(self, value):
        """Validate that the cohort type matches the filters"""
        if not value:
            return value

        cohort_data = {
            "cohort_type": value,
            "is_static": self.initial_data.get(
                "is_static",
                getattr(self.instance, "is_static", False) if self.instance else False,
            ),
            "query": self.initial_data.get(
                "query",
                getattr(self.instance, "query", None) if self.instance else None,
            ),
            "filters": self.initial_data.get(
                "filters",
                getattr(self.instance, "filters", None) if self.instance else None,
            ),
        }

        type_serializer = CohortTypeValidationSerializer(data=cohort_data, team_id=self.context["team_id"])
        if not type_serializer.is_valid():
            # NB: Get the first error message, since it's the only one we're interested in
            if "cohort_type" in type_serializer.errors:
                raise ValidationError(type_serializer.errors["cohort_type"][0])
            raise ValidationError("Invalid cohort type for the given filters")

        return value

    def _handle_static(
        self,
        cohort: Cohort,
        context: dict,
        validated_data: dict,
        person_ids: list[str] | None,
    ) -> None:
        from posthog.tasks.calculate_cohort import (
            insert_cohort_from_feature_flag,
            insert_cohort_from_filters,
            insert_cohort_from_query,
        )

        request = self.context["request"]
        if request.FILES.get("csv") or person_ids:
            if person_ids:
                uuids = validate_person_uuids_exist(self.context["team_id"], person_ids)
                cohort.insert_users_list_by_uuid(uuids, team_id=self.context["team_id"])
            if request.FILES.get("csv"):
                self._calculate_static_by_csv(request.FILES["csv"], cohort)
        elif context.get("from_feature_flag_key"):
            insert_cohort_from_feature_flag.delay(cohort.pk, context["from_feature_flag_key"], self.context["team_id"])
        elif validated_data.get("query"):
            insert_cohort_from_query.delay(cohort.pk, self.context["team_id"])
        elif cohort_filters_have_values(validated_data.get("filters")):
            insert_cohort_from_filters.delay(cohort.pk, self.context["team_id"])
        elif person_ids is not None:
            # Empty list explicitly provided (e.g. MCP creating an empty static cohort to add persons later)
            cohort.insert_users_list_by_uuid([], team_id=self.context["team_id"])
        else:
            raise ValidationError(
                "Invalid source for static cohort. Requires criteria, a csv, feature flag, existing cohort or query."
            )

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:
        request = self.context["request"]
        validated_data["created_by"] = request.user

        has_filter_criteria = cohort_filters_have_values(validated_data.get("filters"))
        if not validated_data.get("is_static"):
            validated_data["is_calculating"] = True
        if validated_data.get("query") and has_filter_criteria:
            raise ValidationError("Cannot set both query and filters at the same time.")

        # Process bytecode for filters if present. Static cohorts define
        # membership by an explicit list of person IDs, so their cohort_type
        # must never be overridden by the filter-based realtime calculation.
        if validated_data.get("filters") and not validated_data.get("is_static"):
            team = Team.objects.get(id=self.context["team_id"])
            clean_filters, computed_cohort_type, _ = validate_filters_and_compute_realtime_support(
                validated_data["filters"],
                team,
                current_cohort_type=validated_data.get("cohort_type"),
            )
            validated_data["filters"] = clean_filters
            validated_data["cohort_type"] = computed_cohort_type

        person_ids = validated_data.pop("_create_static_person_ids", None)
        cohort = Cohort.objects.create(team_id=self.context["team_id"], **validated_data)

        if cohort.is_static:
            if (
                self.context.get("from_cohort_id")
                or self.context.get("from_feature_flag_key")
                or validated_data.get("query")
                or has_filter_criteria
            ):
                cohort.is_calculating = True
                cohort.save(update_fields=["is_calculating"])

            self._handle_static(cohort, self.context, validated_data, person_ids)
            # Refresh from DB to get updated count field set by _insert_users_list_with_batching
            cohort.refresh_from_db()
        elif cohort.query is not None:
            raise ValidationError("Cannot create a dynamic cohort with a query. Set is_static to true.")
        else:
            cohort.enqueue_calculation(initiating_user=request.user)

        report_user_action(
            request.user,
            "cohort created",
            cohort.get_analytics_metadata(),
            team=cohort.team,
            request=request,
        )
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

    def _find_id_column(self, headers: list[str]) -> tuple[int, str, str] | None:
        """Find the index, type, and actual column name of the ID column in headers, with preference order: person_id > distinct_id > email"""
        normalized_headers = [h.strip() for h in headers]
        normalized_lower_headers = [h.lower() for h in normalized_headers]

        # First, look for person_id columns (preferred) - use case-insensitive matching
        person_id_headers_lower = [h.lower() for h in CSVConfig.PERSON_ID_HEADERS]
        for i, header in enumerate(normalized_lower_headers):
            if header in person_id_headers_lower:
                return i, "person_id", normalized_headers[i]

        # Then, look for distinct_id columns
        for i, header in enumerate(normalized_lower_headers):
            if header in CSVConfig.DISTINCT_ID_HEADERS:
                return i, "distinct_id", normalized_headers[i]

        # Finally, look for email columns
        email_headers_lower = [h.lower() for h in CSVConfig.EMAIL_HEADERS]
        for i, header in enumerate(normalized_lower_headers):
            if header in email_headers_lower:
                return i, "email", normalized_headers[i]

        return None

    def _extract_ids_single_column(
        self,
        first_row: list[str],
        reader: Iterator[list[str]],
        skip_header: bool = False,
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

    def _validate_and_process_ids(
        self, ids: list[str], id_type: str, cohort: Cohort, email_property_key: str | None = None
    ) -> None:
        """Final validation and task scheduling"""
        from posthog.tasks.calculate_cohort import calculate_cohort_from_list

        if not ids:
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.NO_VALID_IDS]})

        logger.info(f"Processing CSV upload for cohort {cohort.pk} with {len(ids)} {id_type}s")
        calculate_cohort_from_list.delay(
            cohort.pk,
            ids,
            team_id=self.context["team_id"],
            id_type=id_type,
            email_property_key=email_property_key,
        )

    def _handle_csv_errors(self, e: Exception, cohort: Cohort) -> None:
        """Centralized error handling with consistent exception capture"""

        # Reset calculating flag on error
        cohort.is_calculating = False
        cohort.save(update_fields=["is_calculating"])

        if isinstance(e, UnicodeDecodeError):
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.ENCODING_ERROR]})
        elif isinstance(e, csv.Error):
            capture_exception(
                e,
                additional_properties={
                    "cohort_id": cohort.pk,
                    "team_id": self.context["team_id"],
                },
            )
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.FORMAT_ERROR]})
        elif isinstance(e, ValidationError):
            # If it's already a ValidationError, just re-raise it to preserve format
            raise
        else:
            capture_exception(
                e,
                additional_properties={
                    "cohort_id": cohort.pk,
                    "team_id": self.context["team_id"],
                },
            )
            raise ValidationError({"csv": [CSVConfig.ErrorMessages.GENERIC_ERROR]})

    def _calculate_static_by_csv(self, file, cohort: Cohort) -> None:
        """Main orchestration method for CSV processing - clear high-level flow"""
        # Set calculating flag immediately so UI shows loading state
        cohort.is_calculating = True
        cohort.save(update_fields=["is_calculating"])

        try:
            first_row, reader = self._parse_csv_file(file)

            if self._is_single_column_format(first_row):
                email_property_key: str | None = None
                if first_row and self._is_person_id_header(first_row[0]):
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=True)
                    id_type = "person_id"
                elif first_row and self._is_email_header(first_row[0]):
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=True)
                    id_type = "email"
                    email_property_key = first_row[0].strip()
                else:
                    # Single column format treated as distinct_ids for backwards compatibility
                    ids = self._extract_ids_single_column(first_row, reader, skip_header=False)
                    id_type = "distinct_id"

                self._validate_and_process_ids(ids, id_type, cohort, email_property_key)
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

                id_col, id_type, actual_column_name = result
                ids = self._extract_ids_multi_column(reader, id_col, cohort.pk)
                self._validate_and_process_ids(ids, id_type, cohort, actual_column_name if id_type == "email" else None)

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

    def _cohort_will_be_static(self) -> bool:
        if "is_static" in self.initial_data:
            return str_to_bool(self.initial_data["is_static"])
        return bool(getattr(self.instance, "is_static", False))

    def _effective_filters_after_update(self, attrs: dict) -> dict | None:
        # PATCH may send legacy groups without filters, derive the post-update properties for validation
        instance = cast(Cohort, self.instance)
        filters = attrs.get("filters", instance.filters)
        if filters:
            return filters

        groups = attrs.get("groups", instance.groups)
        if not groups:
            return None

        cohort = Cohort(team=instance.team, filters=None, groups=deepcopy(groups))
        return {"properties": cohort.properties.to_dict()}

    def validate_filters(self, raw: dict):
        """
        1. structural/schema check → pydantic
        2. domain rules (feature-flag gotchas) → bespoke fn
        3. bytecode generation → add bytecode fields to filters
        """
        cohort_will_be_static = self._cohort_will_be_static()

        if cohort_will_be_static and not cohort_filters_have_values(raw):
            return raw
        if not isinstance(raw, dict) or "properties" not in raw:
            raise ValidationError(
                {
                    "detail": "Must contain a 'properties' key with type and values",
                    "type": "validation_error",
                }
            )
        try:
            # Validate structure
            team = self.context.get("get_team", lambda: None)()
            validated = CohortFilters.model_validate(raw, context={"team": team})
            raw = validated.model_dump(exclude_none=True)

        except PydanticValidationError as exc:
            # pydantic → drf error shape
            raise ValidationError(detail=self._cohort_error_message(exc))

        self._validate_feature_flag_constraints(raw, cohort_will_be_static)  # keep your side-rules
        return raw

    def validate(self, attrs: dict) -> dict:
        # Field-level validate_filters only runs when the PATCH body includes `filters`. This
        # object-level guard covers the static-to-dynamic flip when it does not, re-checking the
        # instance's preserved behavioral filters against the feature-flag rule.
        attrs = super().validate(attrs)

        if self.context["request"].method != "PATCH" or self.instance is None:
            return attrs

        instance = cast(Cohort, self.instance)
        if instance.is_static and attrs.get("is_static") is False:
            effective_filters = self._effective_filters_after_update(attrs)
            if effective_filters is not None and cohort_filters_have_values(effective_filters):
                self._validate_feature_flag_constraints(effective_filters, cohort_will_be_static=False)

        return attrs

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

    def _validate_feature_flag_constraints(self, request_filters: dict, cohort_will_be_static: bool):
        if self.context["request"].method != "PATCH":
            return

        parsed_filter = Filter(data=request_filters)
        instance = cast(Cohort, self.instance)
        if instance.is_static and cohort_will_be_static:
            return

        cohort_id = instance.pk

        flags = FeatureFlag.objects.filter(team__project_id=self.context["project_id"], active=True)
        cohort_used_in_flags = any(cohort_id in flag.get_cohort_ids(stop_traversal_at_static=True) for flag in flags)

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
        dependency_cohorts = get_all_cohort_dependencies(nested_cohort, stop_traversal_at_static=True)

        for dependency_cohort in [nested_cohort, *dependency_cohorts]:
            # Static cohorts have materialized membership, any preserved behavioral
            # filters are display-only and never evaluated, so skip them.
            if dependency_cohort.is_static:
                continue
            if cohort_used_in_flags and any(p.type == "behavioral" for p in dependency_cohort.properties.flat):
                raise serializers.ValidationError(
                    detail=f"A cohort dependency ({dependency_cohort.name}) has filters based on events. These cohorts can't be used in feature flags.",
                    code="behavioral_cohort_found",
                )

    def update(self, cohort: Cohort, validated_data: dict, *args: Any, **kwargs: Any) -> Cohort:  # type: ignore
        request = self.context["request"]
        existing_has_criteria = cohort_filters_have_values(cohort.filters)
        filters_changed = "filters" in validated_data and validated_data.get("filters") != cohort.filters

        create_in_folder = validated_data.pop("_create_in_folder", None)
        if create_in_folder is not None:
            cohort._create_in_folder = create_in_folder or None

        cohort.name = validated_data.get("name", cohort.name)
        cohort.description = validated_data.get("description", cohort.description)
        cohort.groups = validated_data.get("groups", cohort.groups)
        cohort.is_static = validated_data.get("is_static", cohort.is_static)
        cohort.cohort_type = validated_data.get("cohort_type", cohort.cohort_type)
        cohort.query = validated_data.get("query", cohort.query)

        # Process bytecode for filters if they're being updated. Static cohorts
        # define membership by an explicit list of person IDs, so their
        # cohort_type must never be overridden by the filter-based calculation.
        if "filters" in validated_data:
            filters = validated_data["filters"]
            if filters and not cohort.is_static:
                clean_filters, computed_cohort_type, _ = validate_filters_and_compute_realtime_support(
                    filters,
                    cohort.team,
                    current_cohort_type=cohort.cohort_type,
                    cohort_count=cohort.count,
                )
                cohort.filters = clean_filters
                cohort.cohort_type = computed_cohort_type
            else:
                cohort.filters = filters

        deleted_state = cast(bool | None, validated_data.get("deleted"))

        incoming_has_criteria = cohort_filters_have_values(validated_data.get("filters"))
        if cohort.is_static and filters_changed and (existing_has_criteria or incoming_has_criteria):
            raise ValidationError(
                "Editing the criteria of a static cohort is not supported yet. Create a new static cohort instead."
            )

        is_deletion_change = deleted_state is not None and cohort.deleted != deleted_state
        if is_deletion_change:
            if deleted_state:
                flags_with_cohort = get_active_flags_using_cohort(cohort)
                if flags_with_cohort:
                    flag_names = [flag.name or flag.key for flag in flags_with_cohort]
                    raise ValidationError(
                        f"This cohort is used in {len(flags_with_cohort)} active feature flag(s): {', '.join(flag_names)}. "
                        "Please remove the cohort from these feature flags before deleting it."
                    )

                # Check if cohort is used in test_account_filters
                teams_with_cohort = Team.objects.filter(
                    project_id=cohort.team.project_id,
                    test_account_filters__contains=[{"type": "cohort"}],
                )
                teams_using_cohort = []
                for team in teams_with_cohort:
                    for filter_item in team.test_account_filters:
                        if filter_item.get("type") == "cohort" and filter_item.get("value") == cohort.id:
                            teams_using_cohort.append(team)
                            break

                if teams_using_cohort:
                    team_names = [team.name for team in teams_using_cohort]
                    raise ValidationError(
                        f"This cohort is used in 'Filter out internal and test users' for {len(teams_using_cohort)} environment(s): {', '.join(team_names)}. "
                        "Please remove the cohort from these test account filters before deleting it."
                    )

                # Check if cohort is used in insights
                insights_using_cohort = get_insights_using_cohort(cohort)

                if insights_using_cohort.exists():
                    count = insights_using_cohort.count()
                    insight_names = [
                        insight.name or insight.derived_name or "Unnamed" for insight in insights_using_cohort[:5]
                    ]
                    names_str = ", ".join(insight_names)
                    if count > 5:
                        names_str = f"{names_str}, and {count - 5} more"
                    raise ValidationError(
                        f"This cohort is used in {count} insight(s): {names_str}. "
                        "Please remove the cohort from these insights before deleting it."
                    )

                # Check if cohort is used as criteria in other cohorts
                dependent_cohorts = get_cohorts_using_cohort(cohort)

                if dependent_cohorts.exists():
                    count = dependent_cohorts.count()
                    cohort_names = [c.name or "Unnamed" for c in dependent_cohorts[:5]]
                    names_str = ", ".join(cohort_names)
                    if count > 5:
                        names_str = f"{names_str}, and {count - 5} more"
                    raise ValidationError(
                        f"This cohort is used as criteria in {count} other cohort(s): {names_str}. "
                        "Please remove this cohort from those cohort definitions before deleting it."
                    )

            relevant_team_ids = Team.objects.filter(project_id=cohort.team.project_id).values_list("id", flat=True)
            if deleted_state is not None:
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
            elif not cohort.is_static:
                cohort.enqueue_calculation(initiating_user=request.user)

        report_user_action(
            request.user,
            "cohort updated",
            {
                **cohort.get_analytics_metadata(),
                "updated_by_creator": request.user == cohort.created_by,
            },
            team=cohort.team,
            request=request,
        )

        return cohort

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Skip when the slim list dropped `filters`; computing
        # `properties.to_dict()` is the expensive part we're avoiding there.
        if "filters" in self.fields:
            representation["filters"] = (
                instance.filters if instance.filters else {"properties": instance.properties.to_dict()}
            )
        return representation


def _used_in_block(page: list[dict], total: int) -> dict[str, Any]:
    """Build one ``{results, total, has_more}`` block of the used_in response."""
    return {"results": page, "total": total, "has_more": total > len(page)}


def _truncate_used_in_queryset(qs: QuerySet) -> tuple[list[dict], int]:
    """Return up to COHORT_USED_IN_PAGE_SIZE rows plus the total count.

    Fetches one row past the cap so the common short-list case derives the total
    from the page itself; the expensive predicate only runs a second time (via
    ``count()``) when the cap is actually exceeded.
    """
    page = list(qs[: COHORT_USED_IN_PAGE_SIZE + 1])
    if len(page) <= COHORT_USED_IN_PAGE_SIZE:
        return page, len(page)
    return page[:COHORT_USED_IN_PAGE_SIZE], qs.count()


def _flags_with_cohort_filters(cohort: Cohort) -> QuerySet[FeatureFlag]:
    """Return non-deleted flags in the cohort's project whose filters contain any cohort property.

    DB-side pre-filter for the ``get_cohort_ids()`` expansion in the callers below, so
    only flags that reference some cohort are loaded into Python instead of every flag
    in the project. Matching any cohort-type property — rather than this specific cohort
    id — is required for correctness: a flag that only transitively references this
    cohort (via another cohort) still directly references some cohort, so this predicate
    is a strict superset of the flags the expansion can match.
    """
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static predicate, no user input)
        FeatureFlag.objects.filter(team__project_id=cohort.team.project_id, deleted=False)
        .extra(where=["""jsonb_path_exists(filters, '$.** ? (@.type == "cohort")')"""])
        .select_related("team")
    )


def _directly_referenced_cohort_ids(flags: list[FeatureFlag]) -> set[int]:
    """Cohort ids each flag references directly in its filter conditions.

    Mirrors the cohort-property walk in ``FeatureFlag.get_cohort_ids``, used to bulk-load
    those cohorts so the expansion doesn't point-query them one at a time.
    """
    return {
        int(prop["value"])
        for flag in flags
        for condition in flag.conditions
        for prop in condition.get("properties", [])
        if prop.get("type") == "cohort" and str(prop.get("value")).lstrip("-").isdigit()
    }


def _filter_flags_referencing_cohort(
    flags: QuerySet[FeatureFlag], cohort: Cohort, *, stop_traversal_at_static: bool = False
) -> list[FeatureFlag]:
    """Expand each flag's cohort references in Python and keep flags that reach this cohort.

    The cache is seeded with the target cohort and bulk-loaded with every cohort the
    flags reference directly, so ``get_cohort_ids()`` only point-queries for cohorts
    nested behind another cohort's filters. Seeding the target also means a soft-deleted
    target still resolves: ``used_in`` reports flags referencing a deleted cohort, which
    matches the insights and cohorts blocks (neither checks the target's deleted state).
    """
    flag_list = list(flags)
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {cohort.id: cohort}
    direct_ids = _directly_referenced_cohort_ids(flag_list) - seen_cohorts_cache.keys()
    if direct_ids:
        for direct_cohort in Cohort.objects.filter(
            pk__in=direct_ids, team__project_id=cohort.team.project_id, deleted=False
        ):
            seen_cohorts_cache[direct_cohort.pk] = direct_cohort
        for missing_id in direct_ids - seen_cohorts_cache.keys():
            seen_cohorts_cache[missing_id] = ""
    return [
        flag
        for flag in flag_list
        if cohort.id
        in flag.get_cohort_ids(
            seen_cohorts_cache=seen_cohorts_cache,
            stop_traversal_at_static=stop_traversal_at_static,
        )
    ]


def get_active_flags_using_cohort(cohort: Cohort) -> list[FeatureFlag]:
    """Return active, non-deleted feature flags that reference this cohort.

    Used by deletion protection: only live flags should block cohort deletion.
    """
    return _filter_flags_referencing_cohort(
        _flags_with_cohort_filters(cohort).filter(active=True),
        cohort,
        stop_traversal_at_static=True,
    )


def get_insights_using_cohort(cohort: Cohort) -> QuerySet[Insight]:
    """Return insights that reference this cohort in their query filters or breakdown.

    The LIKE guard is load-bearing: any insight the jsonpath or breakdown branch can
    match necessarily contains the literal ``"cohort"`` in its query JSON, so the guard
    is a strict superset that short-circuits the recursive (un-indexable) jsonpath for
    insights mentioning no cohort at all. It also keeps the planner's row estimate
    selective; without it, ORDER BY/LIMIT on large teams degrades to a whole-table
    primary-key walk.
    """
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Insight.objects.filter(
            team_id=cohort.team_id,
            deleted=False,
        )
        .extra(
            where=[
                """query::text LIKE %s
                AND (
                    jsonb_path_exists(query, '$.** ? (@.type == "cohort" && @.value == %s)', '{"cohort_id": %s}'::jsonb)
                    OR (
                        query->'source'->'breakdownFilter'->>'breakdown_type' = 'cohort'
                        AND query->'source'->'breakdownFilter'->'breakdown' @> '[%s]'::jsonb
                    )
                )"""
            ],
            params=['%"cohort"%', cohort.id, cohort.id, cohort.id],
        )
        .order_by("id")
    )


def get_cohorts_using_cohort(cohort: Cohort) -> QuerySet[Cohort]:
    """Return other cohorts that include this cohort as criteria."""
    return (
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        Cohort.objects.filter(
            team__project_id=cohort.team.project_id,
            deleted=False,
        )
        .exclude(id=cohort.id)
        .extra(
            where=[
                """jsonb_path_exists(filters, '$.** ? (@.type == "cohort" && @.value == %s)', '{"cohort_id": %s}'::jsonb)"""
            ],
            params=[cohort.id, cohort.id],
        )
        .order_by("id")
    )


@extend_schema(extensions={"x-product": "cohorts"})
@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description=(
                    "Optional. Match against cohort `name`. Returns case-insensitive substring matches and "
                    "fuzzy trigram matches (typos, transpositions, prefix-as-you-type) together, ordered "
                    "exact-first then by relevance; each result's `search_match_type` is `exact` or `similar`. "
                    "When omitted, cohorts are ordered newest-first. Capped at 200 characters; longer queries "
                    "return a 400 error."
                ),
            ),
            OpenApiParameter(
                name="hide_behavioral_cohorts",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                description="Set true to exclude behavioral (event-based) cohorts, which can't be used in feature flags or batch workflow audiences.",
            ),
            OpenApiParameter(
                name="basic",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Return a basic payload that omits the heavy `filters`, `query`, and "
                    "`groups` fields. Useful for pickers that only need id/name/count."
                ),
            ),
        ]
    )
)
class CohortViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Cohort.objects.all()
    serializer_class = CohortSerializer
    scope_object = "cohort"

    def _is_basic_list_request(self) -> bool:
        # `?basic=true` on the list endpoint: trimmed payload + deferred columns.
        # Single source of truth for both the queryset and serializer paths so they
        # can't drift if the default changes or `basic` is wired into another action.
        return self.action == "list" and str_to_bool(self.request.query_params.get("basic", "0"))

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        context["basic_cohort_list"] = self._is_basic_list_request()
        return context

    def _filter_request(self, request: Request, queryset: QuerySet) -> tuple[QuerySet, bool]:
        # Returns (queryset, search_ordered). `search_ordered` is True only when a non-blank
        # search applied trigram relevance ordering, so the caller knows not to re-impose the
        # default ordering on top of it.
        filters = request.GET.dict()
        search_ordered = False

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
                search = request.GET["search"]
                if len(search) > MAX_SEARCH_LENGTH:
                    raise serializers.ValidationError(
                        {"search": f"Search query must be {MAX_SEARCH_LENGTH} characters or fewer."}
                    )
                if normalize_search_term(search):
                    queryset = apply_trigram_search(
                        queryset,
                        search,
                        span_prefix="cohort.search",
                        fields=(NAME_FIELD,),
                        tiebreakers=("-created_at",),
                    )
                    search_ordered = True

        return queryset, search_ordered

    def safely_get_queryset(self, queryset) -> QuerySet:
        search_ordered = False
        if self.action == "list":
            queryset = queryset.filter(deleted=False)

            # Hides behavioral cohorts that can't be used in feature flags from the flag property filter UI.
            # When realtime cohort flag targeting is enabled, realtime cohorts that have been
            # backfilled are allowed through.
            if self.request.query_params.get("hide_behavioral_cohorts", "false").lower() == "true":
                # Avoid circular import: feature_flag imports cohort models
                from products.feature_flags.backend.api.feature_flag import _is_realtime_cohort_flag_targeting_enabled

                allow_realtime_backfilled = _is_realtime_cohort_flag_targeting_enabled(self.request)
                # The flag's cohort typeahead hits this endpoint on every keystroke, so the
                # behavioral set is computed once per team and cached (invalidated on cohort
                # writes); see get_flag_excluded_behavioral_cohort_ids.
                behavioral_cohort_ids = get_flag_excluded_behavioral_cohort_ids(
                    self.team_id, allow_realtime_backfilled=allow_realtime_backfilled
                )
                queryset = queryset.exclude(id__in=behavioral_cohort_ids)

            # add additional filters provided by the client
            queryset, search_ordered = self._filter_request(self.request, queryset)

            # `?basic=true` callers never read these columns, so skip reading them
            # off disk (the serializer drops them too; see CohortSerializer.__init__).
            if self._is_basic_list_request():
                queryset = queryset.defer("filters", "query", "groups")

        last_error_code_subquery = Subquery(
            CohortCalculationHistory.objects.filter(
                cohort=OuterRef("pk"),
                error__isnull=False,
            )
            .exclude(error="")
            .order_by("-started_at")
            .values("error_code")[:1]
        )

        # `created_by` and `team` are forward FKs, so `select_related` JOINs them in
        # one query instead of the two extra round-trips `prefetch_related` costs.
        # `experiment_set` is a reverse relation, so it stays prefetched.
        queryset = (
            queryset.annotate(last_error_code=last_error_code_subquery)
            .select_related("created_by", "team")
            .prefetch_related("experiment_set")
        )

        if not search_ordered:
            queryset = queryset.order_by("-created_at")

        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum number of persons to return per page (defaults to 100).",
            ),
            OpenApiParameter(
                name="offset",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Number of persons to skip before starting to return results.",
            ),
        ],
        responses={200: CohortPersonsResponseSerializer},
    )
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

        tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
        cohort_properties: list[dict] = [{"type": "cohort", "key": "id", "value": cohort.pk}]
        request_properties = request.GET.get("properties")
        if request_properties:
            for prop in json.loads(request_properties):
                # Legacy person filters default to the "exact" operator when none is given;
                # ActorsQuery's PersonPropertyFilter requires it explicitly.
                if prop.get("type") != "cohort":
                    prop.setdefault("operator", "exact")
                cohort_properties.append(prop)

        actors_query = ActorsQuery(
            select=["id"],
            properties=cohort_properties,
            search=request.GET.get("search") or None,
            # Match the legacy PersonQuery ordering (created_at DESC, id DESC) so pagination
            # leads with the newest members; ActorsQuery otherwise defaults to id ASC.
            orderBy=["created_at DESC", "id DESC"],
            limit=filter.limit,
            offset=filter.offset,
        )
        actors_response = ActorsQueryRunner(team=team, query=actors_query).run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        actor_ids = [row[0] for row in actors_response.results]
        with personhog_caller_tag("cohorts/persons"):
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
        uuids = validate_person_uuids_exist(self.team_id, person_ids)
        if len(uuids) == 0:
            raise ValidationError("No valid users to add to cohort")
        cohort.insert_users_list_by_uuid(uuids, team_id=self.team_id)
        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
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

        # Check if person exists and belongs to this team. Only person.uuid is used, so skip the
        # distinct-id fetch.
        with personhog_caller_tag("cohorts/remove-person"):
            person = get_person_by_uuid(team_id=self.team_id, uuid=person_id, distinct_id_limit=0)
        if person is None:
            raise NotFound("Person with this UUID does not exist in the cohort's team")
        person_uuid = person.uuid

        # Remove is idempotent - succeeds even if person wasn't in cohort (handles CH/PG sync issues)
        cohort.remove_user_by_uuid(str(person_uuid), team_id=self.team_id)

        log_activity(
            organization_id=cast(UUIDT, self.organization_id),
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=str(cohort.id),
            scope="Cohort",
            activity="person_removed_manually",
            detail=Detail(changes=[Change(type="Cohort", action="changed")]),
        )
        return Response({"success": True}, status=200)

    @extend_schema(operation_id="cohorts_all_activity_retrieve")
    @action(
        methods=["GET"],
        url_path="activity",
        detail=False,
        required_scopes=["activity_log:read"],
    )
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

    @extend_schema(responses=CohortUsedInResponseSerializer)
    @action(methods=["GET"], detail=True, required_scopes=["cohort:read"])
    def used_in(self, request: request.Request, **kwargs) -> Response:
        cohort: Cohort = self.get_object()
        # Hide references the caller has been denied at the object level, matching the
        # access-level filtering on the flag/insight list endpoints.
        uac = self.user_access_control

        # Access-filter before the Python-side expansion so denied flags are never
        # loaded or expanded.
        flags_qs = uac.filter_queryset_by_access_level(
            _flags_with_cohort_filters(cohort), include_all_if_admin=True
        ).order_by("id")
        flags = _filter_flags_referencing_cohort(flags_qs, cohort, stop_traversal_at_static=True)
        flags_data = [{"id": flag.id, "key": flag.key, "name": flag.name} for flag in flags]

        insights_qs = uac.filter_queryset_by_access_level(get_insights_using_cohort(cohort))
        insights_page, insights_total = _truncate_used_in_queryset(
            insights_qs.values("id", "short_id", "name", "derived_name")
        )
        insights_data = [
            {
                "id": insight["id"],
                "short_id": insight["short_id"],
                "name": insight.get("name") or insight.get("derived_name") or "Unnamed",
            }
            for insight in insights_page
        ]

        cohorts_qs = uac.filter_queryset_by_access_level(get_cohorts_using_cohort(cohort))
        cohorts_page, cohorts_total = _truncate_used_in_queryset(cohorts_qs.values("id", "name"))
        cohorts_data = [{"id": c["id"], "name": c["name"] or "Unnamed"} for c in cohorts_page]

        return Response(
            {
                "feature_flags": _used_in_block(flags_data[:COHORT_USED_IN_PAGE_SIZE], len(flags_data)),
                "insights": _used_in_block(insights_data, insights_total),
                "cohorts": _used_in_block(cohorts_data, cohorts_total),
            }
        )

    def perform_create(self, serializer):
        serializer.save()
        instance = cast(Cohort, serializer.instance)

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated(serializer.context["request"]),
            item_id=instance.id,
            scope="Cohort",
            activity="created",
            detail=Detail(name=instance.name),
        )

    def perform_update(self, serializer):
        instance = cast(Cohort, serializer.instance)
        instance_id = instance.id

        try:
            # Using to_dict() here serializer.save() was changing the instance in memory,
            # so we need to get the before state in a "detached" manner that won't be
            # affected by the serializer.save() call.
            # nosemgrep: idor-lookup-without-team (ID from already team-scoped instance)
            before_update = Cohort.objects.get(pk=instance_id).to_dict()
        except Cohort.DoesNotExist:
            before_update = {}

        serializer.save()

        changes = dict_changes_between("Cohort", previous=before_update, new=instance.to_dict())
        activity = "updated"
        deleted_change = next((change for change in changes if change.field == "deleted"), None)
        if deleted_change:
            if bool(deleted_change.after):
                activity = "deleted"
            elif bool(deleted_change.before):
                activity = "restored"

        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=serializer.context["request"].user,
            was_impersonated=is_impersonated(serializer.context["request"]),
            item_id=instance_id,
            scope="Cohort",
            activity=activity,
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
                        nested_cohort = Cohort.objects.get(
                            pk=cast(str | int, property.value), team__project_id=project_id
                        )
                    except Cohort.DoesNotExist:
                        raise ValidationError("Invalid Cohort ID in filter")

                    if dfs_loop_helper(nested_cohort, seen_cohorts, cohorts_on_path):
                        return True

        cohorts_on_path.remove(current_cohort.pk)
        return False

    return dfs_loop_helper(cohort, set(), set())


# Number of attempts per page when calling the batch evaluation endpoint, including the
# first try. Only transient failures (connection errors, timeouts, 5xx) are retried.
BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS = 3
BATCH_FLAG_EVALUATION_RETRY_BACKOFF_SECONDS = 2.0

COHORT_FLAG_GENERATION_COMPLETED_COUNTER = Counter(
    "cohort_flag_generation_completed_total",
    "Cohort generations from a feature flag that finished, by outcome",
    ["outcome"],  # "success" or a CohortErrorCode value ("flag_changed", "unknown")
)

COHORT_FLAG_GENERATION_DURATION_SECONDS = Histogram(
    "cohort_flag_generation_duration_seconds",
    "Duration of cohort generation from a feature flag in seconds",
    ["outcome"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 14400],
)

COHORT_FLAG_GENERATION_PAGE_RETRIES_COUNTER = Counter(
    "cohort_flag_generation_page_retries_total",
    "Transient batch flag evaluation page failures that were retried against the flags service",
)

COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER = Counter(
    "cohort_flag_generation_eval_errors_total",
    "Per-person evaluation errors reported by the flags service during cohort generation",
)


def _batch_evaluate_flag_page_with_retries(
    *,
    team_id: int,
    project_id: int,
    flag_key: str,
    expected_version: int,
    cursor: int,
    limit: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS):
        if attempt > 0:
            COHORT_FLAG_GENERATION_PAGE_RETRIES_COUNTER.inc()
            time.sleep(BATCH_FLAG_EVALUATION_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
        try:
            return batch_evaluate_flag_for_team(
                team_id=team_id,
                project_id=project_id,
                flag_key=flag_key,
                expected_version=expected_version,
                cursor=cursor,
                limit=limit,
            )
        except FlagVersionConflictError:
            # Permanent: the flag changed mid-run; retrying the same page cannot help.
            raise
        except requests.RequestException as err:
            if (
                isinstance(err, requests.HTTPError)
                and err.response is not None
                and 400 <= err.response.status_code < 500
            ):
                # Permanent client errors (bad request, missing flag, auth misconfiguration).
                raise
            last_error = err
            logger.warning(
                "cohort_from_feature_flag_page_retry",
                team_id=team_id,
                flag_key=flag_key,
                cursor=cursor,
                attempt=attempt + 1,
                error=str(err),
            )
    assert last_error is not None
    raise last_error


def get_cohort_actors_for_feature_flag(cohort_id: int, flag: str, team_id: int, batchsize: int = 1_000) -> None:
    """
    Populate a static cohort with the persons matched by a feature flag.

    Evaluation happens in the Rust feature-flags service (the same code path as live
    /flags evaluation) via its internal cursor-paged batch endpoint; this task only
    orchestrates paging and inserts the matched person UUIDs into the cohort.
    """
    # Flag and cohort lookups are deliberately project-scoped (team__project_id), matching
    # how flags resolve everywhere else. Multi-team projects ("environments") are
    # deprecated, so a project has exactly one team and this cannot cross team boundaries.
    project_id = Team.objects.only("project_id").get(pk=team_id).project_id
    cohort = Cohort.objects.get(pk=cohort_id, team__project_id=project_id)
    # The enqueue site set is_calculating=True before dispatching, so every exit has to
    # clear it. On the guard paths there is nothing to evaluate, so finalize as a clean
    # no-op run rather than leaving the cohort stuck "calculating" with no record of why.
    try:
        feature_flag = FeatureFlag.objects.get(team__project_id=project_id, key=flag)
    except FeatureFlag.DoesNotExist:
        cohort._safe_save_cohort_state(team_id=team_id, processing_error=None)
        return

    if not feature_flag.active or feature_flag.aggregation_group_type_index is not None:
        cohort._safe_save_cohort_state(team_id=team_id, processing_error=None)
        return

    # Pin the flag definition for the whole run: every page sends this version and the
    # service refuses to evaluate under any other, so a run can never mix two
    # definitions of the flag. Nullable versions coerce to 0 on both sides.
    expected_version = feature_flag.version or 0

    started_at = timezone.now()
    start_monotonic = time.monotonic()
    eval_errors_count = 0
    try:
        uuids_to_add_to_cohort: list[str] = []
        cursor = 0
        while True:
            page = _batch_evaluate_flag_page_with_retries(
                team_id=team_id,
                project_id=project_id,
                flag_key=feature_flag.key,
                expected_version=expected_version,
                cursor=cursor,
                limit=batchsize,
            )
            uuids_to_add_to_cohort.extend(page["matched_person_uuids"])
            page_errors_count = page.get("errors_count") or 0
            if page_errors_count:
                COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER.inc(page_errors_count)
            eval_errors_count += page_errors_count

            if len(uuids_to_add_to_cohort) >= batchsize:
                cohort.insert_users_list_by_uuid(
                    uuids_to_add_to_cohort, batchsize=batchsize, team_id=team_id, raise_on_error=True
                )
                uuids_to_add_to_cohort = []

            next_cursor = page["next_cursor"]
            if next_cursor is None:
                break
            if next_cursor <= cursor:
                raise RuntimeError(f"Batch flag evaluation cursor did not advance (got {next_cursor} after {cursor})")
            cursor = next_cursor

        # Always flush, even when empty: insert_users_list_by_uuid recomputes the cohort
        # count and clears is_calculating via _safe_save_cohort_state. Re-running after a
        # partial failure is safe because inserts dedupe on (cohort_id, person_id).
        # raise_on_error surfaces an insert failure so the except below records it rather
        # than letting a partial insert be counted as a successful generation.
        cohort.insert_users_list_by_uuid(
            uuids_to_add_to_cohort, batchsize=batchsize, team_id=team_id, raise_on_error=True
        )

        if eval_errors_count:
            logger.warning(
                "cohort_from_feature_flag_eval_errors",
                cohort_id=cohort_id,
                team_id=team_id,
                flag_key=feature_flag.key,
                errors_count=eval_errors_count,
            )

        COHORT_FLAG_GENERATION_COMPLETED_COUNTER.labels(outcome="success").inc()
        COHORT_FLAG_GENERATION_DURATION_SECONDS.labels(outcome="success").observe(time.monotonic() - start_monotonic)
    except Exception as err:
        logger.exception(
            "cohort_from_feature_flag_failed",
            cohort_id=cohort_id,
            team_id=team_id,
            flag_key=feature_flag.key,
            error=str(err),
        )
        capture_exception(err, additional_properties={"cohort_id": cohort_id, "team_id": team_id})
        error_code = (
            CohortErrorCode.FLAG_CHANGED if isinstance(err, FlagVersionConflictError) else CohortErrorCode.UNKNOWN
        )
        COHORT_FLAG_GENERATION_COMPLETED_COUNTER.labels(outcome=error_code.value).inc()
        COHORT_FLAG_GENERATION_DURATION_SECONDS.labels(outcome=error_code.value).observe(
            time.monotonic() - start_monotonic
        )
        # Finalize cohort state before writing the history row. _safe_save_cohort_state
        # swallows its own failures, so if the history insert ran first and raised, the
        # cohort would stay is_calculating=True with no Celery retry to recover it
        # (max_retries=0). Worst case in this order is a finalized cohort missing a
        # history row, rather than one stuck calculating forever.
        cohort._safe_save_cohort_state(team_id=team_id, processing_error=err)
        # The history `error` field is user-visible via the calculation history API, so
        # store the friendly message; raw exception details (internal URLs, instance
        # config) stay in logs and error tracking only.
        CohortCalculationHistory.objects.create(
            team_id=team_id,
            cohort=cohort,
            filters=cohort.filters or {},
            started_at=started_at,
            finished_at=timezone.now(),
            error=get_friendly_error_message(error_code),
            error_code=error_code,
        )
        raise
