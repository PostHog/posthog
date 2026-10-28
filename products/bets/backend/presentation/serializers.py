from uuid import uuid4

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from ..facade.enums import (
    BetActionKind,
    BetActivityResource,
    BetDirection,
    BetPhase,
    BetStatus,
    BetStatusChange,
    BetTile,
    BetWorkAction,
    EvidenceKind,
    IdeaAssessment,
    IdeaOutcome,
    IdeaSource,
    ModelStep,
    StepBilling,
    WorkKind,
    WorkStage,
)


class BetsActivitySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable activity entry identifier.")
    at = serializers.DateTimeField(help_text="Recorded time of this event.")
    title = serializers.CharField(help_text="Summary of the recorded event.")
    detail = serializers.CharField(allow_blank=True, help_text="Related work or changed fields.")
    resource = serializers.ChoiceField(choices=BetActivityResource.choices, help_text="Native resource to open.")
    resource_id = serializers.CharField(allow_blank=True, help_text="Identifier or URL of the linked native resource.")


class BetsSecondaryMetricSerializer(serializers.Serializer):
    insight = serializers.CharField(max_length=32, help_text="Saved PostHog insight used as a guardrail.")
    name = serializers.CharField(max_length=255, help_text="Name of the guardrail metric.")
    direction = serializers.ChoiceField(
        choices=BetDirection.choices, default=BetDirection.INCREASE, help_text="Whether higher or lower is better."
    )
    max_regression = serializers.FloatField(
        min_value=0, max_value=1, default=0.05, help_text="Largest tolerated relative regression, 0.05 for 5%."
    )


class BetsWriteSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField(default=uuid4, help_text="Stable ID for retrying creation without duplicates.")
    title = serializers.CharField(max_length=160, help_text="Short name of the bet.")
    statement = serializers.CharField(max_length=10000, help_text="What you believe will improve and why.")
    audience = serializers.CharField(
        max_length=500, allow_blank=True, default="", help_text="People this bet aims to help."
    )
    area = serializers.CharField(max_length=120, allow_blank=True, default="", help_text="Product area for filtering.")
    repository = serializers.RegexField(
        r"^[\w.-]+/[\w.-]+$",
        max_length=255,
        required=False,
        help_text="Main GitHub repository in owner/repository form. Defaults to the first of repositories.",
    )
    repositories = serializers.ListField(
        child=serializers.RegexField(r"^[\w.-]+/[\w.-]+$", max_length=255),
        max_length=10,
        required=False,
        help_text="GitHub repositories Bets reads and changes, in owner/repository form. The first is the main one.",
    )
    goal_insight = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        help_text="Saved insight with one series that measures the goal. Leave empty and describe the goal instead.",
    )
    goal_description = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        help_text="How to measure the goal, in words, when no saved insight fits. Bets finds or creates the insight.",
    )
    goal_metric = serializers.CharField(max_length=255, help_text="Name of the primary metric.")
    ideas = serializers.ListField(
        child=serializers.CharField(max_length=255),
        max_length=5,
        required=False,
        default=list,
        help_text="The owner's own ideas. The Scout checks each one against the data before anyone chooses.",
    )
    secondary_metrics = BetsSecondaryMetricSerializer(
        many=True, default=list, help_text="Guardrails that must not get worse."
    )
    target = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True,
        help_text="Target value of the primary metric. Set it after Bets finds the insight for a described goal.",
    )
    direction = serializers.ChoiceField(
        choices=BetDirection.choices, default=BetDirection.INCREASE, help_text="Whether higher or lower is better."
    )
    unit = serializers.CharField(max_length=32, allow_blank=True, default="", help_text="Display unit, for example %.")
    budget_cents = serializers.IntegerField(
        min_value=0, max_value=1000000000, help_text="Budget for this bet in USD cents."
    )

    def validate(self, attrs: dict) -> dict:
        secondary = attrs.get("secondary_metrics", self.context.get("secondary_metrics", []))
        ids = [item["insight"] for item in secondary]
        if len(ids) > 5:
            raise serializers.ValidationError({"secondary_metrics": "Choose up to five guardrails."})
        primary = attrs.get("goal_insight", self.context.get("primary_insight", ""))
        if len(ids) != len(set(ids)) or primary in ids:
            raise serializers.ValidationError({"secondary_metrics": "Each insight can appear only once."})
        if "repositories" in attrs or "repository" in attrs:
            repositories = list(dict.fromkeys(attrs.get("repositories") or [attrs.get("repository", "")]))
            if not any(repositories):
                raise serializers.ValidationError({"repositories": "Choose at least one repository."})
            attrs["repositories"] = repositories
            attrs["repository"] = repositories[0]
        if not self.partial:
            if "repository" not in attrs:
                raise serializers.ValidationError({"repositories": "Choose at least one repository."})
            if not attrs.get("goal_insight") and not attrs.get("goal_description", "").strip():
                raise serializers.ValidationError(
                    {"goal_insight": "Choose a saved insight, or describe how to measure the goal."}
                )
            if attrs.get("goal_insight") and attrs.get("target") is None:
                raise serializers.ValidationError({"target": "Set the value to reach."})
        return attrs


class BetsMetricSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Metric name.")
    unit = serializers.CharField(allow_blank=True, help_text="Display unit from the saved insight.")
    values = serializers.ListField(child=serializers.FloatField(), help_text="Values in chronological order.")
    dates = serializers.ListField(child=serializers.CharField(), help_text="Dates corresponding to values.")
    current = serializers.FloatField(allow_null=True, help_text="Latest available value.")
    change = serializers.FloatField(allow_null=True, help_text="Percentage change across the displayed period.")
    message = serializers.CharField(allow_blank=True, help_text="Reason a measurement is unavailable.")


class BetsMoneySerializer(serializers.Serializer):
    allocated_cents = serializers.IntegerField(help_text="Allocated budget in USD cents.")
    spent_cents = serializers.IntegerField(help_text="Settled spend in USD cents.")
    reserved_cents = serializers.IntegerField(help_text="Budget held for running work in USD cents.")
    available_cents = serializers.IntegerField(help_text="Uncommitted budget in USD cents.")


class BetsIdeaResultSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=IdeaOutcome.choices, required=False, help_text="How the idea ended.")
    variant = serializers.CharField(required=False, help_text="Variant kept when the experiment ended.")
    verdict = serializers.CharField(required=False, help_text="Why the experiment ended this way.")
    exposures = serializers.DictField(
        child=serializers.IntegerField(), required=False, help_text="People exposed per variant."
    )
    primary = serializers.DictField(
        child=serializers.ListField(child=serializers.FloatField(), allow_null=True),
        required=False,
        help_text="Relative effect interval on the primary metric per test variant.",
    )
    smallest_sample = serializers.IntegerField(required=False, help_text="People in the smallest group.")
    harmed_guardrails = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="Guardrails that got worse."
    )
    summary = serializers.CharField(required=False, help_text="What we learned.")


class BetsEvidenceSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=EvidenceKind.choices, help_text="What the evidence link points to.")
    label = serializers.CharField(help_text="Short text that describes the evidence.")  # type: ignore[assignment]
    url = serializers.CharField(help_text="Link to the PostHog data, or chart:<id> for a chart in the report.")


class BetsPlanSerializer(serializers.Serializer):
    days = serializers.IntegerField(allow_null=True, help_text="Days the experiment runs before Bets reads the result.")
    mde = serializers.FloatField(allow_null=True, help_text="Smallest relative change, in percent, the run can find.")
    audience = serializers.IntegerField(allow_null=True, help_text="People a day who see the change.")
    weekly = serializers.BooleanField(help_text="Whether the metric has a weekly pattern.")
    too_long = serializers.BooleanField(help_text="Whether the plan is longer than four weeks.")
    mean = serializers.FloatField(allow_null=True, help_text="Mean of the goal metric used for the plan.")
    variance = serializers.FloatField(allow_null=True, help_text="Variance of the goal metric used for the plan.")
    proposed_days = serializers.IntegerField(
        allow_null=True, help_text="New length after the re-plan, waiting for the owner to extend or stop."
    )
    approved = serializers.BooleanField(help_text="Whether the owner approved this plan.")
    replanned = serializers.BooleanField(help_text="Whether Bets re-planned from the control group.")


class BetsPlanInputSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=2, max_value=365, help_text="Days the experiment runs.")
    mde = serializers.FloatField(min_value=0.1, max_value=100, help_text="Smallest change worth finding, in percent.")
    audience = serializers.IntegerField(min_value=1, help_text="People a day who see the change.")


class BetsWorkSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Work item ID.")
    goal_version = serializers.IntegerField(help_text="Goal revision this work belongs to.")
    kind = serializers.ChoiceField(choices=WorkKind.choices, help_text="Tracking check or idea.")
    stage = serializers.ChoiceField(choices=WorkStage.choices, help_text="Where this work is in its lifecycle.")
    title = serializers.CharField(help_text="Work title.")
    summary = serializers.CharField(allow_blank=True, help_text="The idea's evidence and proposed change.")
    note = serializers.CharField(allow_blank=True, help_text="Latest status in plain language.")
    pr_url = serializers.CharField(allow_blank=True, help_text="Pull request opened by the task.")
    pr_state = serializers.CharField(allow_blank=True, help_text="Pull request state from Tasks.")
    flag_key = serializers.CharField(allow_blank=True, help_text="Feature flag the change ships behind.")
    experiment_id = serializers.IntegerField(allow_null=True, help_text="Native experiment measuring the idea.")
    result = BetsIdeaResultSerializer(help_text="Measured outcome, effect intervals, exposures and verdict.")
    task_id = serializers.UUIDField(allow_null=True, help_text="Native task doing the work.")
    task_status = serializers.CharField(help_text="Latest native task run status.")
    attempts = serializers.IntegerField(help_text="Task runs started for this work.")
    spent_cents = serializers.IntegerField(help_text="Settled cost in USD cents.")
    created_at = serializers.DateTimeField(help_text="When the work started.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the work finished.")
    source = serializers.ChoiceField(choices=IdeaSource.choices, help_text="Who proposed the idea.")  # type: ignore[assignment]
    assessment = serializers.ChoiceField(
        choices=[("", "None"), *IdeaAssessment.choices],
        allow_blank=True,
        help_text="The Scout's check of the idea against the data.",
    )
    evidence = BetsEvidenceSerializer(many=True, help_text="Links to the PostHog data behind the idea.")
    report_id = serializers.UUIDField(allow_null=True, help_text="Scout report that describes the idea.")
    dismissed_reason = serializers.CharField(allow_blank=True, help_text="Why the owner dismissed the idea.")
    moves_metric = serializers.CharField(allow_blank=True, help_text="The metric the Scout expects this idea to move.")
    plan = BetsPlanSerializer(help_text="Experiment plan for an idea.")


class BetsNextActionSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable identifier.")
    bet_id = serializers.UUIDField(help_text="Bet requiring attention.")
    bet_title = serializers.CharField(help_text="Name of the bet.")
    title = serializers.CharField(help_text="What needs attention.")
    description = serializers.CharField(allow_blank=True, help_text="What to do next.")
    label = serializers.CharField(help_text="Why this needs attention.")  # type: ignore[assignment]
    work_id = serializers.UUIDField(allow_null=True, help_text="Related work item.")
    url = serializers.CharField(allow_blank=True, help_text="Pull request or other place to act.")


class BetsStateActionSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Button text.")  # type: ignore[assignment]
    kind = serializers.ChoiceField(choices=BetActionKind.choices, help_text="What the button opens or does.")
    primary = serializers.BooleanField(help_text="Whether the owner must act, rather than an optional step.")
    work_id = serializers.UUIDField(allow_null=True, help_text="Work item the button opens or acts on.")
    work_action = serializers.ChoiceField(
        choices=BetWorkAction.choices,
        allow_null=True,
        help_text="Work action the button runs on the work item, or empty to open it.",
    )
    url = serializers.CharField(allow_blank=True, help_text="Pull request to open.")


class BetsScoutStateSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="What the Scout does now, in a few words.")  # type: ignore[assignment]
    reason = serializers.CharField(help_text="Why the Scout does this, in one or two sentences.")


class BetsStateSerializer(serializers.Serializer):
    phase = serializers.ChoiceField(choices=BetPhase.choices, help_text="What the bet is doing now.")
    tile = serializers.ChoiceField(choices=BetTile.choices, help_text="Which part of Bets the status line is about.")
    headline = serializers.CharField(help_text="Main status line.")
    detail = serializers.CharField(allow_blank=True, help_text="Second status line.")
    subject = serializers.CharField(allow_blank=True, help_text="Title of the idea the status line is about.")
    work_id = serializers.UUIDField(allow_null=True, help_text="Work item the status line is about.")
    working = serializers.BooleanField(help_text="Whether Bets works on this step now.")
    action = BetsStateActionSerializer(allow_null=True, help_text="The owner's next step for this status.")
    alternative = BetsStateActionSerializer(allow_null=True, help_text="A second choice next to the action.")
    scout = BetsScoutStateSerializer(help_text="What the Scout does now.")
    ready_ideas = serializers.IntegerField(help_text="Ideas ready for the owner to choose.")
    checking_ideas = serializers.IntegerField(help_text="Owner ideas that wait for the Scout's check.")
    build_blocked = serializers.CharField(allow_blank=True, help_text="Why no idea can be built now, or empty.")
    can_add_idea = serializers.BooleanField(help_text="Whether the bet takes new owner ideas.")
    needs_you = serializers.BooleanField(help_text="Whether the bet waits for the owner.")
    actions = BetsNextActionSerializer(many=True, help_text="Everything the owner must do, most urgent first.")


class BetsOwnerSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="User who owns the bet.")
    name = serializers.CharField(help_text="Display name.")
    email = serializers.CharField(allow_blank=True, help_text="Email address.")


class BetsEntrySerializer(serializers.Serializer):
    owner = BetsOwnerSerializer(help_text="The person who owns and controls this bet.")
    id = serializers.UUIDField(help_text="Bet ID.")
    reference = serializers.IntegerField(help_text="Human-readable bet number.")
    title = serializers.CharField(help_text="Bet name.")
    statement = serializers.CharField(help_text="What we believe and why.")
    audience = serializers.CharField(allow_blank=True, help_text="Intended audience.")
    area = serializers.CharField(allow_blank=True, help_text="Product area.")
    repository = serializers.CharField(help_text="Main connected repository.")
    repositories = serializers.ListField(
        child=serializers.CharField(), help_text="Connected repositories. The first is the main one."
    )
    goal_insight = serializers.CharField(allow_blank=True, help_text="Primary metric insight.")
    goal_description = serializers.CharField(
        allow_blank=True, help_text="How the owner described the goal measure, when they wrote it in words."
    )
    goal_metric = serializers.CharField(help_text="Primary metric name.")
    secondary_metrics = BetsSecondaryMetricSerializer(many=True, help_text="Guardrails.")
    target = serializers.DecimalField(
        max_digits=20, decimal_places=4, allow_null=True, help_text="Primary metric target, empty until set."
    )
    direction = serializers.ChoiceField(choices=BetDirection.choices, help_text="Whether higher or lower is better.")
    unit = serializers.CharField(allow_blank=True, help_text="Primary metric unit.")
    status = serializers.ChoiceField(choices=BetStatus.choices, help_text="Bet lifecycle state.")
    baseline_value = serializers.FloatField(allow_null=True, help_text="Primary metric when the bet started running.")
    baseline_at = serializers.DateTimeField(allow_null=True, help_text="When the baseline was recorded.")
    money = BetsMoneySerializer(help_text="Budget accounting.")
    metric = BetsMetricSerializer(help_text="Primary metric history.")
    spend_pending = serializers.BooleanField(help_text="Some task usage is still settling.")
    ideas_tried = serializers.IntegerField(help_text="Ideas measured to a conclusion.")
    ideas_won = serializers.IntegerField(help_text="Ideas that improved the primary metric.")
    needs_you = serializers.BooleanField(
        help_text="Whether the bet waits for the owner, for example to choose an idea."
    )
    state = BetsStateSerializer(help_text="What the bet does now and what it needs from the owner.")
    updated_at = serializers.DateTimeField(help_text="Latest change.")


class BetsScoutSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(help_text="Native Scout configuration.")
    name = serializers.CharField(help_text="Native Scout name.")
    enabled = serializers.BooleanField(help_text="Whether the Scout may run.")
    running = serializers.BooleanField(help_text="Whether the Scout is searching for an idea right now.")


class BetsSpendPointSerializer(serializers.Serializer):
    at = serializers.DateTimeField(help_text="When this usage settled.")
    spent_cents = serializers.IntegerField(help_text="Total settled spend up to this time, in USD cents.")


class BetsDetailSerializer(BetsEntrySerializer):
    is_owner = serializers.BooleanField(help_text="Whether the viewer owns this bet and can change it.")
    spend_history = BetsSpendPointSerializer(many=True, help_text="Cumulative settled spend over time.")
    goal_version = serializers.IntegerField(help_text="Current goal revision.")
    goal_met_since = serializers.DateTimeField(
        allow_null=True,
        help_text="When the goal metric reached the target; the bet counts as reached after the confirm time.",
    )
    work = BetsWorkSerializer(many=True, help_text="Tracking checks and ideas, newest first.")
    secondary_values = BetsMetricSerializer(many=True, help_text="Current guardrail readings.")
    scout = BetsScoutSerializer(allow_null=True, help_text="The Scout looking for ideas.")
    next_action = BetsNextActionSerializer(allow_null=True, help_text="The most urgent next step.")
    can_edit = serializers.BooleanField(help_text="Whether the viewer can change this bet.")


class BetsStepModelSerializer(serializers.Serializer):
    step = serializers.ChoiceField(choices=ModelStep.choices, help_text="Which step uses this model.")
    model = serializers.CharField(allow_blank=True, help_text="Model ID, or empty for the project default.")
    reasoning_effort = serializers.CharField(allow_blank=True, help_text="Reasoning effort, or empty for the default.")
    billing = serializers.ChoiceField(choices=StepBilling.choices, help_text="Who pays for this step's model use.")
    model_label = serializers.CharField(help_text="Display name of the model.")


class BetsModelOptionSerializer(serializers.Serializer):
    model = serializers.CharField(help_text="Model ID.")
    label = serializers.CharField(help_text="Display name.")  # type: ignore[assignment]
    runtime_adapter = serializers.CharField(help_text="Runtime that drives the model.")
    supported_efforts = serializers.ListField(child=serializers.CharField(), help_text="Reasoning efforts it supports.")
    cost_multiplier = serializers.CharField(allow_null=True, help_text="Cost compared with the baseline model.")


class BetsSettingsSerializer(serializers.Serializer):
    budget_cents = serializers.IntegerField(help_text="Project budget in USD cents.")
    north_star_insight = serializers.CharField(allow_blank=True, help_text="Saved insight for the project North Star.")
    models = BetsStepModelSerializer(many=True, help_text="Model and billing for each step.")
    model_options = BetsModelOptionSerializer(many=True, help_text="Models a step may use.")
    plan_available = serializers.BooleanField(help_text="Whether a connected ChatGPT plan can pay for unattended runs.")
    min_run_hours = serializers.IntegerField(help_text="Shortest experiment run in hours. Zero lets the plan decide.")
    mde_percent = serializers.FloatField(help_text="Smallest relative change, in percent, an experiment plans to find.")
    goal_confirm_hours = serializers.IntegerField(
        help_text="Hours the goal metric must stay at the target before the bet counts as reached."
    )


class BetsStepModelWriteSerializer(serializers.Serializer):
    model = serializers.CharField(
        allow_blank=True, max_length=200, help_text="Model ID, or empty for the project default."
    )
    reasoning_effort = serializers.CharField(allow_blank=True, max_length=20, default="", help_text="Reasoning effort.")
    billing = serializers.ChoiceField(choices=StepBilling.choices, help_text="Who pays for this step's model use.")


class BetsStepModelsWriteSerializer(serializers.Serializer):
    scout = BetsStepModelWriteSerializer(required=False, help_text="Model for the Scout.")
    tracking = BetsStepModelWriteSerializer(required=False, help_text="Model for tracking checks.")
    idea = BetsStepModelWriteSerializer(required=False, help_text="Model for building ideas.")


class BetsSettingsWriteSerializer(serializers.Serializer):
    budget_cents = serializers.IntegerField(
        min_value=0, max_value=1000000000, required=False, help_text="Project budget in USD cents."
    )
    north_star_insight = serializers.CharField(
        max_length=32, allow_blank=True, required=False, help_text="Saved insight for the project North Star."
    )
    min_run_hours = serializers.IntegerField(
        min_value=0,
        max_value=24 * 60,
        required=False,
        help_text="Shortest experiment run in hours. Zero lets the plan decide.",
    )
    mde_percent = serializers.FloatField(
        min_value=0.1,
        max_value=100,
        required=False,
        help_text="Smallest relative change, in percent, an experiment plans to find.",
    )
    goal_confirm_hours = serializers.IntegerField(
        min_value=0,
        max_value=24 * 60,
        required=False,
        help_text="Hours the goal metric must stay at the target before the bet counts as reached.",
    )
    step_models = BetsStepModelsWriteSerializer(required=False, help_text="Model and billing per step.")


@extend_schema_serializer(many=False)
class BetsOverviewSerializer(serializers.Serializer):
    next_actions = BetsNextActionSerializer(many=True, help_text="Everything that needs attention, most urgent first.")
    bets = BetsEntrySerializer(many=True, help_text="Bets in this project.")
    north_star = BetsMetricSerializer(help_text="Current project North Star.")
    settings = BetsSettingsSerializer(help_text="Project budget, North Star and models.")
    allocated_cents = serializers.IntegerField(help_text="Total allocated project budget.")
    unallocated_cents = serializers.IntegerField(help_text="Project budget still available.")
    can_edit = serializers.BooleanField(help_text="Whether the viewer can create or change bets.")


class BetsMetricPreviewQuerySerializer(serializers.Serializer):
    insight = serializers.CharField(max_length=32, help_text="Short ID of the saved insight to preview.")


class BetsStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=BetStatusChange.choices, help_text="Resume, pause or close the bet.")


class BetsWorkActionSerializer(serializers.Serializer):
    work_id = serializers.UUIDField(help_text="Work item belonging to this bet.")
    action = serializers.ChoiceField(
        choices=BetWorkAction.choices,
        help_text="Build a proposed idea, dismiss it, retry stuck work, drop an idea in progress, or extend its experiment.",
    )
    reason = serializers.CharField(
        max_length=1000, required=False, allow_blank=True, default="", help_text="Why the idea is dismissed."
    )
    plan = BetsPlanInputSerializer(required=False, help_text="The experiment plan the owner approves with a build.")


class BetsIdeaSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, help_text="The owner's idea, in one sentence.")
