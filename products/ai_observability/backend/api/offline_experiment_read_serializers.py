from collections.abc import Mapping
from dataclasses import replace
from typing import cast
from uuid import UUID

from django.http import QueryDict

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from products.ai_observability.backend.api.offline_experiment_serializers import (
    ItemPayloadField,
    ResultPayloadField,
    ResultValueField,
    _StrictDataclassSerializer,
)
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineExperiment,
    PayloadState,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition
from products.ai_observability.backend.offline_evaluation_read_types import OfflineReadQuery
from products.ai_observability.backend.offline_evaluation_service import OfflineEvaluationValidationError
from products.ai_observability.backend.score_definition_configs import ScoreDefinitionConfigField


class OfflineEmptyQuerySerializer(serializers.Serializer):
    def to_internal_value(self, data: object) -> dict[str, object]:
        if isinstance(data, Mapping) and data:
            raise serializers.ValidationError({str(key): ["This parameter is not supported."] for key in data})
        return {}


class OfflinePageQuerySerializer(_StrictDataclassSerializer[OfflineReadQuery]):
    limit = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=100, help_text="Page size, from 1 to 100. Defaults to 50."
    )
    cursor = serializers.CharField(
        required=False, max_length=2048, help_text="Continuation cursor returned by the previous page."
    )

    class Meta:
        dataclass = OfflineReadQuery
        fields = ["limit", "cursor"]

    def to_internal_value(self, data: object) -> OfflineReadQuery:
        if isinstance(data, QueryDict):
            repeated = {key: ["Supply this parameter once."] for key in data if len(data.getlist(key)) != 1}
            if repeated:
                raise serializers.ValidationError(repeated)
        try:
            return super().to_internal_value(data)
        except OfflineEvaluationValidationError as error:
            raise serializers.ValidationError(error.errors) from error


class OfflineResultQuerySerializer(OfflinePageQuerySerializer):
    scorer_version_ids = serializers.CharField(
        required=False, max_length=739, help_text="Comma-separated list of at most 20 distinct scorer-version UUIDs."
    )

    class Meta(OfflinePageQuerySerializer.Meta):
        fields = [*OfflinePageQuerySerializer.Meta.fields, "scorer_version_ids"]

    def validate_scorer_version_ids(self, value: str) -> tuple[UUID, ...]:
        values = value.split(",")
        if len(values) > 20:
            raise serializers.ValidationError("Select at most 20 distinct scorer versions.")
        versions = tuple(cast(UUID, serializers.UUIDField().run_validation(version)) for version in values)
        if len(set(versions)) != len(versions):
            raise serializers.ValidationError("Select distinct scorer versions.")
        return versions


class OfflineSummaryQuerySerializer(OfflineResultQuerySerializer):
    scorer_definition_id = serializers.UUIDField(
        required=False, help_text="Restrict results to this scorer definition."
    )

    class Meta(OfflineResultQuerySerializer.Meta):
        fields = [*OfflineResultQuerySerializer.Meta.fields, "scorer_definition_id"]


class OfflineExperimentQuerySerializer(OfflineSummaryQuerySerializer):
    date_from = serializers.DateTimeField(
        required=False, help_text="Inclusive execution start time, in ISO 8601 format."
    )
    date_to = serializers.DateTimeField(required=False, help_text="Exclusive execution end time, in ISO 8601 format.")
    search = serializers.CharField(required=False, max_length=400, help_text="Search experiment names.")
    run_source = serializers.CharField(
        required=False, max_length=16, help_text="Filter ci, local, scheduled, or not_specified for omitted run source."
    )
    statuses = serializers.CharField(
        required=False,
        max_length=32,
        help_text="Comma-separated uploading, completed, or failed states. History defaults to completed; lists include all.",
    )
    suite_key = serializers.CharField(required=False, max_length=255, help_text="Exact evaluation suite identifier.")
    dataset_source = serializers.CharField(required=False, max_length=255, help_text="Exact dataset source.")
    dataset_identifier = serializers.CharField(
        required=False, max_length=255, help_text="Exact durable dataset identifier."
    )
    dataset_revision_identifier = serializers.CharField(
        required=False, max_length=255, help_text="Exact durable dataset revision identifier."
    )
    application_version = serializers.CharField(required=False, max_length=255, help_text="Exact application revision.")
    model_version = serializers.CharField(required=False, max_length=255, help_text="Exact model revision.")
    prompt_version = serializers.CharField(required=False, max_length=255, help_text="Exact prompt revision.")

    class Meta(OfflineSummaryQuerySerializer.Meta):
        fields = [
            *OfflineSummaryQuerySerializer.Meta.fields,
            "date_from",
            "date_to",
            "search",
            "run_source",
            "statuses",
            "suite_key",
            "dataset_source",
            "dataset_identifier",
            "dataset_revision_identifier",
            "application_version",
            "model_version",
            "prompt_version",
        ]

    def validate_statuses(self, value: str) -> tuple[str, ...]:
        values = tuple(value.split(","))
        if len(set(values)) != len(values) or any(state not in OfflineExperiment.Status.values for state in values):
            raise serializers.ValidationError("Select distinct uploading, completed, or failed states.")
        return values

    def validate_run_source(self, value: str) -> str:
        if value not in [*OfflineExperiment.RunSource.values, "not_specified"]:
            raise serializers.ValidationError("Use ci, local, scheduled, or not_specified.")
        return value

    def validate(self, attrs: OfflineReadQuery) -> OfflineReadQuery:
        if attrs.run_source == "not_specified":
            return replace(attrs, run_source=None, run_source_is_null=True)
        return attrs


class OfflineExperimentReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable experiment UUID.")
    name = serializers.CharField(help_text="Experiment name.")
    run_source = serializers.ChoiceField(
        choices=OfflineExperiment.RunSource.choices, allow_null=True, help_text="Execution source."
    )
    status = serializers.ChoiceField(choices=OfflineExperiment.Status.choices, help_text="Upload lifecycle state.")
    started_at = serializers.DateTimeField(help_text="Caller-supplied execution time.")
    created_at = serializers.DateTimeField(help_text="First server acceptance time.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="Server closure time, or null while uploading.")
    expected_item_count = serializers.IntegerField(allow_null=True, help_text="Declared expected items, when supplied.")
    expected_result_count = serializers.IntegerField(
        allow_null=True, help_text="Declared expected results across all scorers."
    )
    accepted_item_count = serializers.IntegerField(
        help_text="Observed items, including items without a selected scorer result."
    )
    visible_result_count = serializers.IntegerField(
        allow_null=True, help_text="Results visible to this caller; unavailable without scorer-read scope."
    )
    visible_scorer_definition_count = serializers.IntegerField(
        allow_null=True, help_text="Distinct visible scorer definitions."
    )
    visible_scorer_version_count = serializers.IntegerField(
        allow_null=True, help_text="Distinct visible scorer versions."
    )
    result_counts_available = serializers.BooleanField(
        help_text="Whether this credential can read scorer-dependent counts."
    )
    result_count_scope = serializers.CharField(
        help_text="authorized for visible-result counts, or unavailable without scorer-read scope."
    )
    suite_key = serializers.CharField(allow_null=True, help_text="Durable suite identifier.")
    dataset_source = serializers.CharField(allow_null=True, help_text="Dataset provider or source.")
    dataset_identifier = serializers.CharField(allow_null=True, help_text="Durable dataset identifier.")
    dataset_revision_identifier = serializers.CharField(
        allow_null=True, help_text="Durable dataset revision identifier."
    )
    dataset_revision_id = serializers.UUIDField(
        allow_null=True, help_text="Optional hosted revision navigation reference."
    )
    application_version = serializers.CharField(allow_null=True, help_text="Application revision under evaluation.")
    model_version = serializers.CharField(allow_null=True, help_text="Model revision under evaluation.")
    prompt_version = serializers.CharField(allow_null=True, help_text="Prompt revision under evaluation.")


class OfflineScorerVersionReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Exact immutable scorer-version UUID.")
    definition_id = serializers.UUIDField(help_text="Stable scorer definition UUID.")
    version = serializers.IntegerField(help_text="Version number within the definition.")
    kind = serializers.ChoiceField(choices=ScoreDefinition.Kind.choices, help_text="Scorer value kind.")
    name = serializers.CharField(help_text="Current scorer display name.")
    description = serializers.CharField(allow_blank=True, help_text="Current scorer description.")
    archived = serializers.BooleanField(help_text="Whether the scorer is archived.")
    config = ScoreDefinitionConfigField(help_text="Pinned immutable configuration used to interpret these results.")


class OfflineResultReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable result UUID.")
    item_id = serializers.UUIDField(help_text="Item evaluated by this result.")
    scorer = OfflineScorerVersionReadSerializer(help_text="Pinned scorer version.")
    status = serializers.ChoiceField(choices=OfflineEvaluationResult.Status.choices, help_text="Evaluation outcome.")
    value = ResultValueField(allow_null=True, help_text="Typed score for ok outcomes; null for other outcomes.")
    error_code = serializers.CharField(allow_null=True, help_text="Optional evaluator error code.")
    evaluator_trace_id = serializers.CharField(
        allow_null=True, help_text="Optional evaluator trace navigation reference."
    )
    evaluated_at = serializers.DateTimeField(allow_null=True, help_text="Caller-supplied evaluation time.")
    accepted_at = serializers.DateTimeField(help_text="Original server acceptance time.")
    payload_state = serializers.ChoiceField(choices=PayloadState.choices, help_text="Result payload storage state.")
    payload_expires_at = serializers.DateTimeField(
        allow_null=True, help_text="Payload retention deadline; cleanup is not yet enabled."
    )


class OfflineItemReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable item UUID.")
    experiment_id = serializers.UUIDField(help_text="Owning experiment UUID.")
    case_key = serializers.CharField(allow_null=True, help_text="Optional stable case identifier.")
    trial = serializers.CharField(allow_null=True, help_text="Optional trial identifier within a case.")
    dataset_item_identifier = serializers.CharField(allow_null=True, help_text="Durable dataset item identifier.")
    dataset_item_version_identifier = serializers.CharField(
        allow_null=True, help_text="Durable dataset item-version identifier."
    )
    dataset_item_version_id = serializers.UUIDField(
        allow_null=True, help_text="Optional hosted item-version navigation reference."
    )
    application_trace_id = serializers.CharField(
        allow_null=True, help_text="Optional application trace navigation reference."
    )
    accepted_at = serializers.DateTimeField(help_text="Original server acceptance time.")
    payload_state = serializers.ChoiceField(choices=PayloadState.choices, help_text="Item payload storage state.")
    payload_expires_at = serializers.DateTimeField(
        allow_null=True, help_text="Payload retention deadline; cleanup is not yet enabled."
    )
    results = OfflineResultReadSerializer(
        many=True, help_text="Cells for explicitly selected scorer versions; empty when none selected."
    )


class OfflineItemPayloadReadSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Owning item UUID.")
    payload_state = serializers.ChoiceField(choices=PayloadState.choices, help_text="Durable payload storage state.")
    payload_expires_at = serializers.DateTimeField(allow_null=True, help_text="Payload retention deadline.")
    available = serializers.BooleanField(help_text="Whether the stored payload is currently available.")

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["data"] = ItemPayloadField(
            allow_null=True,
            help_text="Stored item payload, preserving omitted properties and JSON null; null if unavailable.",
        )
        return fields


class OfflineResultPayloadReadSerializer(OfflineItemPayloadReadSerializer):
    id = serializers.UUIDField(help_text="Owning result UUID.")

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["data"] = ResultPayloadField(
            allow_null=True, help_text="Stored reasoning/error payload; null if unavailable."
        )
        return fields


class OfflineStatusCountsSerializer(serializers.Serializer):
    ok = serializers.IntegerField(help_text="Successful results.")
    error = serializers.IntegerField(help_text="Evaluator errors.")
    skipped = serializers.IntegerField(help_text="Skipped evaluations.")
    not_applicable = serializers.IntegerField(help_text="Not-applicable evaluations.")


class OfflineCategorySummarySerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Category key from the pinned configuration.")
    count = serializers.IntegerField(help_text="Successful results selecting this category.")
    rate = serializers.FloatField(
        allow_null=True, help_text="Selection count divided by successful result count; null with no successes."
    )

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["label"] = serializers.CharField(help_text="Category label from the pinned configuration.")
        return fields


class OfflineScorerSummarySerializer(serializers.Serializer):
    scorer = OfflineScorerVersionReadSerializer(help_text="Exact scorer version summarized.")
    observed_item_count = serializers.IntegerField(
        help_text="All observed experiment items, independent of scorer selection or item pagination."
    )
    result_count = serializers.IntegerField(help_text="Submitted results for this scorer version, across all statuses.")
    status_counts = OfflineStatusCountsSerializer(help_text="Counts for each submitted outcome.")
    missing_result_count = serializers.IntegerField(
        help_text="Observed items without a result for this version; not the number of all intended missing items."
    )
    distinct_case_count = serializers.IntegerField(help_text="Distinct non-null case keys in observed items.")
    items_with_case_key_count = serializers.IntegerField(help_text="Observed items with case keys.")
    items_without_case_key_count = serializers.IntegerField(help_text="Observed items without case keys.")
    trial_item_count = serializers.IntegerField(help_text="Observed items with trial identifiers.")
    distinct_trial_count = serializers.IntegerField(
        help_text="Distinct case/trial identities; trial-only items remain independent."
    )
    mean = serializers.FloatField(
        allow_null=True, help_text="Numeric mean of successful scores only; null for other kinds or no successes."
    )
    true_count = serializers.IntegerField(
        allow_null=True, help_text="Successful boolean true results; null for other kinds."
    )
    false_count = serializers.IntegerField(
        allow_null=True, help_text="Successful boolean false results; null for other kinds."
    )
    true_rate = serializers.FloatField(
        allow_null=True, help_text="Boolean true fraction among successes; null with no successes or for other kinds."
    )
    categories = OfflineCategorySummarySerializer(
        many=True, help_text="Pinned categorical distribution; multiselect rates may sum above one."
    )


class OfflineHistoryPointSerializer(serializers.Serializer):
    experiment = OfflineExperimentReadSerializer(help_text="Experiment execution and cohort context.")
    summary = OfflineScorerSummarySerializer(help_text="Complete summary for one experiment and scorer version.")


@extend_schema_serializer(many=False)
class OfflinePageSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total authorized rows matching the filters, independent of this page.")
    next_cursor = serializers.CharField(allow_null=True, help_text="Continuation cursor, or null after the final page.")


class OfflineExperimentPageSerializer(OfflinePageSerializer):
    results = OfflineExperimentReadSerializer(many=True, help_text="Experiment page.")


class OfflineItemPageSerializer(OfflinePageSerializer):
    results = OfflineItemReadSerializer(many=True, help_text="Item page.")


class OfflineResultPageSerializer(OfflinePageSerializer):
    results = OfflineResultReadSerializer(many=True, help_text="Result page.")


class OfflineSummaryPageSerializer(OfflinePageSerializer):
    results = OfflineScorerSummarySerializer(
        many=True, help_text="Scorer-version summary page; each group includes all matching results."
    )


class OfflineHistoryPageSerializer(OfflinePageSerializer):
    results = OfflineHistoryPointSerializer(many=True, help_text="Experiment/scorer-version history page.")
