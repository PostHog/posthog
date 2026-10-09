"""DRF serializers for cloud_agents."""

from __future__ import annotations

from enum import Enum
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..facade.api import MAX_IDLE_MINUTES, MIN_IDLE_MINUTES
from ..facade.contracts import RepositoryRef, RunDTO
from ..facade.enums import (
    BillingMode,
    CallerKind,
    CloudAgentReasoningEffort,
    CloudAgentRunStatus,
    CloudAgentRunStatusReason,
    CloudAgentSessionStatus,
    InferenceBilling,
    InferenceMode,
    SizeName,
    UsageGroupBy,
)

REPOSITORY_REGEX = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
MAX_TAGS = 20
URL_MAX_LENGTH = 2000
PROMPT_MAX_LENGTH = 64000
MAX_METADATA_PAIRS = 16
METADATA_KEY_MAX_LENGTH = 64
METADATA_VALUE_MAX_LENGTH = 512
IDEMPOTENCY_KEY_MAX_LENGTH = 100
MAX_ESTIMATE_MINUTES = 24 * 60


class LabeledEnumField(serializers.ChoiceField):
    """A choice field that gives the view an enum member and writes the value of the member."""

    def __init__(self, enum_class: Any, **kwargs: Any) -> None:
        self.enum_class = enum_class
        super().__init__(choices=enum_class.choices, **kwargs)

    def to_internal_value(self, data: Any) -> Any:
        return self.enum_class(super().to_internal_value(data))

    def to_representation(self, value: Any) -> Any:
        return super().to_representation(value.value if isinstance(value, Enum) else value)


def _tags_field(**kwargs: Any) -> serializers.ListField:
    return serializers.ListField(
        child=serializers.CharField(max_length=50),
        max_length=MAX_TAGS,
        **kwargs,
    )


@extend_schema_field({"type": "object", "additionalProperties": True})
class JSONObjectField(serializers.JSONField):
    """A JSON object with any keys, for example a JSON Schema."""

    default_error_messages = {"not_an_object": "This value must be a JSON object."}

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        value = super().to_internal_value(data)
        if not isinstance(value, dict):
            self.fail("not_an_object")
        return value


class CloudAgentRepositorySerializer(serializers.Serializer):
    name = serializers.RegexField(
        REPOSITORY_REGEX, max_length=255, help_text="GitHub repository, in the format `owner/name`."
    )
    initial_branch = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        help_text="Branch that the agent starts from. Null uses the default branch of the repository.",
    )

    def to_internal_value(self, data: Any) -> RepositoryRef:
        return RepositoryRef(**super().to_internal_value(data))


class RunDefaultsSerializer(serializers.Serializer):
    """The run defaults that a preset and the project settings share. A null value sets no default."""

    repositories = CloudAgentRepositorySerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text="Default repositories that the agent works in. Only one repository is supported for now. Null sets no default.",
    )
    model = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        help_text="Default model for the agent. Null lets PostHog select the model.",
    )
    reasoning_effort = LabeledEnumField(
        CloudAgentReasoningEffort,
        required=False,
        allow_null=True,
        help_text=(
            "How much the model reasons before it answers. A model supports only some of the values. "
            "Null uses the default of the model."
        ),
    )
    size = LabeledEnumField(
        SizeName,
        required=False,
        allow_null=True,
        help_text="Default sandbox size, as `<vCPU>x<memory in GiB>`. Null uses the product default.",
    )
    inference = LabeledEnumField(
        InferenceMode,
        required=False,
        allow_null=True,
        help_text=(
            "How the agent pays for model usage. `auto` uses your own subscription when one is connected "
            "for the runtime, and PostHog inference otherwise. Null uses the product default."
        ),
    )
    instructions = serializers.CharField(
        max_length=20000,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Instructions that the agent gets before the prompt. Project instructions come first, "
            "then preset instructions, then the instructions of the run."
        ),
    )
    create_pr = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether the agent opens a pull request when it finishes. Null uses the product default.",
    )
    idle_minutes = serializers.IntegerField(
        min_value=MIN_IDLE_MINUTES,
        max_value=MAX_IDLE_MINUTES,
        required=False,
        allow_null=True,
        help_text=(
            f"How many minutes the sandbox waits with no activity before it stops, from {MIN_IDLE_MINUTES} to "
            f"{MAX_IDLE_MINUTES}. The run is then `idle`, and a message continues it. While the agent is in the "
            "middle of a turn, the sandbox waits 10 minutes at least. Null uses the product default, 10."
        ),
    )
    output_schema = JSONObjectField(
        required=False,
        allow_null=True,
        help_text=(
            "A JSON Schema with `type` set to `object`. When set, the agent must return a JSON result that "
            "matches it, and the run returns the result in `result.output`. Null asks for no structured result."
        ),
    )


class CloudAgentPresetWriteFieldsSerializer(RunDefaultsSerializer):
    description = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, help_text="What this preset is for."
    )
    tags = _tags_field(required=False, help_text="Tags added to every run that uses this preset.")


class CloudAgentPresetCreateSerializer(CloudAgentPresetWriteFieldsSerializer):
    name = serializers.CharField(
        max_length=100,
        help_text="Name of the preset. It is unique in the project, without regard to case.",
    )


class CloudAgentPresetUpdateSerializer(CloudAgentPresetWriteFieldsSerializer):
    name = serializers.CharField(
        max_length=100,
        required=False,
        help_text="Name of the preset. It is unique in the project, without regard to case.",
    )


class CloudAgentPresetSerializer(RunDefaultsSerializer):
    id = serializers.UUIDField(help_text="ID of the preset.")
    name = serializers.CharField(help_text="Name of the preset.")
    description = serializers.CharField(allow_blank=True, help_text="What this preset is for.")
    tags = _tags_field(help_text="Tags added to every run that uses this preset.")
    created_by = serializers.IntegerField(
        source="created_by_id", allow_null=True, help_text="ID of the user who created the preset."
    )
    created_at = serializers.DateTimeField(help_text="When the preset was created.")
    updated_at = serializers.DateTimeField(help_text="When the preset was last changed.")


class CloudAgentSettingsUpdateSerializer(RunDefaultsSerializer):
    default_preset = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="ID of the preset that a run uses when it names no preset. Null sets no default preset.",
    )


class CloudAgentSettingsSerializer(RunDefaultsSerializer):
    default_preset = serializers.UUIDField(
        source="default_preset_id",
        allow_null=True,
        help_text="ID of the preset that a run uses when it names no preset.",
    )
    max_concurrent_runs = serializers.IntegerField(
        help_text="How many runs the project can have active at the same time."
    )
    create_rate_per_hour = serializers.IntegerField(help_text="How many runs the project can start in one hour.")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="When the settings were last changed.")


# --- Runs ---


class CloudAgentRunCreateSerializer(RunDefaultsSerializer):
    prompt = serializers.CharField(
        max_length=PROMPT_MAX_LENGTH,
        help_text="The task for the agent, in plain language.",
    )
    repositories = CloudAgentRepositorySerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text=(
            "The repositories that the agent works in. Only one repository is supported for now. Required "
            "unless the preset or the project settings set a default."
        ),
    )
    preset = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        help_text=(
            "ID or name of the preset whose defaults the run uses. Null uses the default preset of the "
            "project, when one is set."
        ),
    )
    tags = _tags_field(required=False, help_text="Tags for the run. The tags of the preset are added to them.")
    metadata = serializers.DictField(
        child=serializers.CharField(max_length=METADATA_VALUE_MAX_LENGTH, allow_blank=True),
        required=False,
        help_text=(
            f"Your own key and value pairs, stored with the run and returned with it. At most "
            f"{MAX_METADATA_PAIRS} pairs. Keys and values are strings."
        ),
    )

    def validate_metadata(self, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_METADATA_PAIRS:
            raise serializers.ValidationError(f"Use at most {MAX_METADATA_PAIRS} metadata pairs.")
        if any(len(key) > METADATA_KEY_MAX_LENGTH for key in value):
            raise serializers.ValidationError(f"A metadata key can have {METADATA_KEY_MAX_LENGTH} characters at most.")
        return value


class CloudAgentRunMessageSerializer(serializers.Serializer):
    content = serializers.CharField(
        max_length=PROMPT_MAX_LENGTH, help_text="The follow-up message for the agent, in plain language."
    )


class CloudAgentRunListQuerySerializer(serializers.Serializer):
    status = LabeledEnumField(
        CloudAgentRunStatus,
        required=False,
        help_text=(
            "Return only the runs with this status. A status filter covers the newest 1,000 runs that are "
            "active, for `queued` and `running`, or that have no agent at work, for `idle` and `done`."
        ),
    )
    preset_id = serializers.UUIDField(required=False, help_text="Return only the runs that used this preset.")
    repository = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Return runs whose repository contains this text.",
    )
    tag = serializers.CharField(max_length=50, required=False, help_text="Return only the runs that have this tag.")
    created_after = serializers.DateTimeField(
        required=False, help_text="Return only the runs created at or after this time, in ISO 8601 format."
    )
    created_before = serializers.DateTimeField(
        required=False, help_text="Return only the runs created before this time, in ISO 8601 format."
    )


class CloudAgentRunPresetRefSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="preset_id", help_text="ID of the preset.")
    name = serializers.CharField(source="preset_name", help_text="Name of the preset.")


class CloudAgentSizeSerializer(serializers.Serializer):
    name = LabeledEnumField(SizeName, help_text="Name of the size, as `<vCPU>x<memory in GiB>`.")
    vcpu = serializers.IntegerField(help_text="Number of vCPUs of the sandbox.")
    memory_gib = serializers.IntegerField(help_text="Memory of the sandbox in GiB.")
    price_per_hour_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        normalize_output=True,
        help_text="Compute price of one hour of this size in US dollars, as a decimal string.",
    )


class CloudAgentRunConfigSerializer(serializers.Serializer):
    """Reads a run: the stored configuration is in `config`, and the priced size is on the run."""

    model = serializers.CharField(source="config.model", allow_null=True, help_text="Model that the agent uses.")
    reasoning_effort = LabeledEnumField(
        CloudAgentReasoningEffort,
        source="config.reasoning_effort",
        allow_null=True,
        help_text="How much the model reasons before it answers. Null uses the default of the model.",
    )
    size = CloudAgentSizeSerializer(help_text="Sandbox size of the run. It is fixed for the life of the run.")
    inference = LabeledEnumField(
        InferenceMode,
        source="config.inference",
        help_text=(
            "How the run pays for model usage: `posthog` for PostHog inference, `own_subscription` for the "
            "subscription of the user."
        ),
    )
    create_pr = serializers.BooleanField(
        source="config.create_pr", help_text="Whether the agent opens a pull request when it finishes."
    )
    idle_minutes = serializers.IntegerField(
        source="config.idle_minutes",
        help_text="How many minutes the sandbox waits with no activity before it stops.",
    )
    output_schema = JSONObjectField(
        source="config.output_schema",
        allow_null=True,
        help_text="The JSON Schema that the result of the agent must match. Null when the run has none.",
    )
    instructions_applied = serializers.SerializerMethodField(
        help_text="Whether the agent got instructions from the run, its preset or the project settings."
    )

    @extend_schema_field(serializers.BooleanField())
    def get_instructions_applied(self, run: RunDTO) -> bool:
        return bool(run.config.instructions)


class CloudAgentRunResultSerializer(serializers.Serializer):
    pr_url = serializers.URLField(allow_null=True, help_text="URL of the pull request that the agent opened last.")
    pr_urls = serializers.ListField(
        child=serializers.URLField(), help_text="URLs of all pull requests that the agent opened."
    )
    summary = serializers.CharField(allow_null=True, help_text="Summary of the work, written by the agent.")
    output = JSONObjectField(
        allow_null=True,
        help_text=(
            "The JSON result that the agent returned for the `output_schema` of the run. Null when the run "
            "has no schema, or when the agent returned no result yet."
        ),
    )


def _usd_field(help_text: str, **kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=14, decimal_places=4, help_text=help_text, **kwargs)


def _seconds_field(help_text: str, **kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=16, decimal_places=3, help_text=help_text, **kwargs)


class CloudAgentRunCostSerializer(serializers.Serializer):
    compute_usd = _usd_field(
        "Compute cost in US dollars, as a decimal string. Null until the first sandbox reports usage.",
        allow_null=True,
    )
    inference_usd = _usd_field(
        "Model usage cost in US dollars, as a decimal string. Null when the run uses your own subscription, "
        "because you pay the model provider directly.",
        allow_null=True,
    )
    total_usd = _usd_field(
        "Sum of the compute cost and the model usage cost, as a decimal string. Null until the compute cost is known.",
        allow_null=True,
    )
    vcpu_seconds = _seconds_field("vCPU seconds that the run used.", allow_null=True)
    gib_seconds = _seconds_field("GiB seconds of memory that the run used.", allow_null=True)
    billing_mode = LabeledEnumField(
        BillingMode, help_text="`billed` when the project pays for the run, `unbilled` when it does not."
    )
    inference_billing = LabeledEnumField(
        InferenceBilling, allow_null=True, help_text="Who pays for the model usage of the run."
    )
    final = serializers.BooleanField(
        help_text="Whether the cost is final. The cost can still change for a short time after the run stops."
    )


class CloudAgentAgentSessionSerializer(serializers.Serializer):
    index = serializers.IntegerField(help_text="Position of the session in the run, from 1.")
    status = LabeledEnumField(
        CloudAgentSessionStatus,
        help_text="`queued` waits for a sandbox, `running` has an agent at work, and `ended` has no sandbox.",
    )
    started_at = serializers.DateTimeField(allow_null=True, help_text="When the agent started work in this session.")
    ended_at = serializers.DateTimeField(allow_null=True, help_text="When the session ended.")


class CloudAgentRunCreatedBySerializer(serializers.Serializer):
    id = serializers.IntegerField(source="created_by_id", help_text="ID of the user.")
    email = serializers.CharField(source="created_by_email", allow_null=True, help_text="Email address of the user.")


class CloudAgentRunSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the run.")
    status = LabeledEnumField(
        CloudAgentRunStatus,
        help_text=(
            "`queued` waits for a sandbox. `running` has an agent at work. `idle` has no sandbox, and a "
            "message continues the run. `done` is final, and a message is refused."
        ),
    )
    status_reason = LabeledEnumField(
        CloudAgentRunStatusReason,
        allow_null=True,
        help_text=(
            "Why the run is `idle` or `done`. Null while the run is `queued` or `running`. An `idle` run has "
            "`turn_closed` when the agent finished its turn, `timed_out`, `credit_spent`, `provision_failed` "
            "or `unexpected_failure`. A `done` run has `finished` when its pull request was merged, `closed` "
            "when every pull request was closed and not merged, or `cancelled`."
        ),
    )
    status_detail = serializers.CharField(
        allow_null=True,
        help_text="What the status reason means for you and what to do next. Null when there is nothing to add.",
    )
    created_at = serializers.DateTimeField(help_text="When the run was created.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="When the agent first started work.")
    ended_at = serializers.DateTimeField(
        allow_null=True, help_text="When the last agent session ended. Null while the run is `queued` or `running`."
    )
    updated_at = serializers.DateTimeField(help_text="When the run last changed.")
    prompt = serializers.CharField(help_text="The task that the run started with.")
    repositories = CloudAgentRepositorySerializer(many=True, help_text="The repositories that the agent works in.")
    preset = serializers.SerializerMethodField(help_text="The preset that the run used. Null when it used none.")
    config = CloudAgentRunConfigSerializer(source="*", help_text="The configuration that the run uses.")
    result = CloudAgentRunResultSerializer(help_text="What the agent produced.")
    cost = CloudAgentRunCostSerializer(help_text="What the run cost.")
    agent_sessions = CloudAgentAgentSessionSerializer(
        many=True,
        help_text="The agent sessions of the run, oldest first. A message to an `idle` run starts a new session.",
    )
    tags = _tags_field(help_text="Tags of the run, including the tags of its preset.")
    metadata = serializers.DictField(
        child=serializers.CharField(allow_blank=True), help_text="Your own key and value pairs."
    )
    created_by = serializers.SerializerMethodField(
        help_text="The user who started the run. Null when the user no longer exists."
    )
    caller = LabeledEnumField(
        CallerKind,
        source="caller_kind",
        help_text="`api` for an API client, `app` for the PostHog app, `internal` for a PostHog product.",
    )

    @extend_schema_field(CloudAgentRunPresetRefSerializer(allow_null=True))
    def get_preset(self, run: RunDTO) -> Any:
        return CloudAgentRunPresetRefSerializer(run).data if run.preset_id is not None else None

    @extend_schema_field(CloudAgentRunCreatedBySerializer(allow_null=True))
    def get_created_by(self, run: RunDTO) -> Any:
        return CloudAgentRunCreatedBySerializer(run).data if run.created_by_id is not None else None


class CloudAgentRunMessageResponseSerializer(serializers.Serializer):
    resumed = serializers.BooleanField(
        help_text=(
            "True when the message started a new agent session, because the run was `idle`. False when "
            "the running agent got the message."
        )
    )
    run = CloudAgentRunSerializer(help_text="The run after the message.")


class CloudAgentSandboxSessionUsageSerializer(serializers.Serializer):
    vcpu = serializers.DecimalField(
        max_digits=8, decimal_places=3, normalize_output=True, help_text="Number of vCPUs of the sandbox."
    )
    memory_gib = serializers.DecimalField(
        max_digits=8, decimal_places=3, normalize_output=True, help_text="Memory of the sandbox in GiB."
    )
    started_at = serializers.DateTimeField(help_text="When the sandbox started.")
    ended_at = serializers.DateTimeField(allow_null=True, help_text="When the sandbox stopped. Null while it is up.")
    seconds = serializers.IntegerField(help_text="How many seconds of the sandbox count for the cost.")
    cost_usd = _usd_field("Compute cost of the sandbox in US dollars, as a decimal string.")
    waived = serializers.BooleanField(help_text="Whether PostHog waived the cost of this sandbox.")


class CloudAgentRunUsageSerializer(serializers.Serializer):
    run_id = serializers.UUIDField(help_text="ID of the run.")
    cost = CloudAgentRunCostSerializer(help_text="What the run cost up to now.")
    sessions = CloudAgentSandboxSessionUsageSerializer(many=True, help_text="The sandboxes of the run, oldest first.")


class CloudAgentRunEventsSerializer(serializers.Serializer):
    events = serializers.ListField(
        child=serializers.DictField(),
        help_text=(
            "The stored events of the run, oldest first, across all agent sessions. Each event is one "
            "agent protocol message with the time it was recorded."
        ),
    )
    truncated = serializers.BooleanField(
        help_text=(
            "True when the event log is too large to return in full. The response then has the earliest "
            "agent sessions that fit."
        )
    )


# --- Catalog, estimate and usage ---


class CloudAgentModelSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="ID of the model. Use it as `model` when you start a run.")
    name = serializers.CharField(help_text="Display name of the model.")
    runtime_adapter = serializers.CharField(help_text="The agent runtime that drives the model.")
    is_default = serializers.BooleanField(help_text="Whether a run with no model uses this model.")


class CloudAgentRateCardSerializer(serializers.Serializer):
    vcpu_hour_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        normalize_output=True,
        help_text="Price of one vCPU for one hour in US dollars, as a decimal string.",
    )
    memory_gib_hour_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        normalize_output=True,
        help_text="Price of one GiB of memory for one hour in US dollars, as a decimal string.",
    )
    version = serializers.CharField(help_text="Version of the price list.")


class CloudAgentLimitsSerializer(serializers.Serializer):
    max_concurrent_runs = serializers.IntegerField(
        help_text="How many runs the project can have active at the same time."
    )
    create_rate_per_hour = serializers.IntegerField(help_text="How many runs the project can start in one hour.")


class CloudAgentCatalogSerializer(serializers.Serializer):
    sizes = CloudAgentSizeSerializer(many=True, help_text="The sandbox sizes that a run can use.")
    models = CloudAgentModelSerializer(many=True, help_text="The models that a run can use.")
    inference_modes = serializers.ListField(
        child=LabeledEnumField(InferenceMode), help_text="The values that `inference` accepts."
    )
    rates = CloudAgentRateCardSerializer(help_text="The compute prices that the size prices come from.")
    limits = CloudAgentLimitsSerializer(help_text="The limits of this project.")


class CloudAgentEstimateQuerySerializer(serializers.Serializer):
    size = LabeledEnumField(SizeName, help_text="Sandbox size to price, as `<vCPU>x<memory in GiB>`.")
    minutes = serializers.IntegerField(
        min_value=1, max_value=MAX_ESTIMATE_MINUTES, help_text="How many minutes the sandbox is up."
    )


class CloudAgentEstimateSerializer(serializers.Serializer):
    size = LabeledEnumField(SizeName, help_text="The sandbox size that was priced.")
    minutes = serializers.IntegerField(help_text="How many minutes the sandbox is up.")
    price_per_hour_usd = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        normalize_output=True,
        help_text="Compute price of one hour of this size in US dollars, as a decimal string.",
    )
    estimate_usd = _usd_field(
        "Compute cost for the given minutes in US dollars, as a decimal string. Model usage is not included."
    )


class CloudAgentUsageQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(
        required=False, help_text="Start of the range, in ISO 8601 format. The default is 30 days before `date_to`."
    )
    date_to = serializers.DateTimeField(
        required=False, help_text="End of the range, not included, in ISO 8601 format. The default is now."
    )
    group_by = LabeledEnumField(
        UsageGroupBy,
        required=False,
        default=UsageGroupBy.DAY,
        help_text="`day` gives one bucket for each UTC day. `preset` gives one bucket for each preset.",
    )


class CloudAgentUsageTotalsSerializer(serializers.Serializer):
    runs = serializers.IntegerField(help_text="Number of runs.")
    compute_usd = _usd_field("Compute cost in US dollars, as a decimal string.")
    inference_usd = _usd_field(
        "Model usage cost in US dollars, as a decimal string. Runs on your own subscription add nothing."
    )
    total_usd = _usd_field("Sum of the compute cost and the model usage cost, as a decimal string.")
    vcpu_seconds = _seconds_field("vCPU seconds used.")
    gib_seconds = _seconds_field("GiB seconds of memory used.")


class CloudAgentUsageBucketSerializer(serializers.Serializer):
    key = serializers.CharField(
        allow_null=True,
        help_text=(
            "The UTC date of the bucket for `group_by=day`. The preset ID for `group_by=preset`, or null "
            "for the runs that used no preset."
        ),
    )
    name = serializers.CharField(
        source="label", allow_null=True, help_text="Name of the preset for `group_by=preset`. Null for other buckets."
    )
    usage = CloudAgentUsageTotalsSerializer(help_text="Usage of the runs in this bucket.")


class CloudAgentUsageSummarySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(help_text="Start of the range.")
    date_to = serializers.DateTimeField(help_text="End of the range, not included.")
    group_by = LabeledEnumField(UsageGroupBy, help_text="How the buckets are grouped.")
    totals = CloudAgentUsageTotalsSerializer(help_text="Usage of all runs created in the range.")
    buckets = CloudAgentUsageBucketSerializer(many=True, help_text="Usage for each day or for each preset.")
