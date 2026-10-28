from typing import NoReturn

from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import BetDirection, BetStatus, IdeaAssessment, IdeaSource, LedgerKind, WorkKind, WorkStage


class BetsModel(ProductTeamModel):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        abstract = True


class BetsSettings(BetsModel):
    budget_cents = models.PositiveBigIntegerField(default=0)
    north_star_insight = models.CharField(max_length=32, blank=True, default="")
    next_reference = models.PositiveIntegerField(default=1001)
    step_models = models.JSONField(default=dict, blank=True)
    min_run_hours = models.PositiveIntegerField(default=0)
    mde_percent = models.FloatField(default=30)
    goal_confirm_hours = models.PositiveIntegerField(default=72)

    class Meta(BetsModel.Meta):
        db_table = "bets_settings"
        constraints = [models.UniqueConstraint(fields=["team_id"], name="bets_settings_team")]


class Bet(ModelActivityMixin, BetsModel):
    reference = models.PositiveIntegerField()
    owner_id = models.BigIntegerField()
    title = models.CharField(max_length=160)
    statement = models.TextField()
    audience = models.CharField(max_length=500, blank=True, default="")
    area = models.CharField(max_length=120, blank=True, default="")
    repository = models.CharField(max_length=255)
    repositories = models.JSONField(default=list, blank=True)
    goal_insight = models.CharField(max_length=32, blank=True, default="")
    goal_description = models.TextField(blank=True, default="")
    goal_metric = models.CharField(max_length=255)
    secondary_metrics = models.JSONField(default=list, blank=True)
    target = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    direction = models.CharField(max_length=8, choices=BetDirection.choices, default=BetDirection.INCREASE)
    unit = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=BetStatus.choices, default=BetStatus.SETTING_UP)
    goal_version = models.PositiveIntegerField(default=1)
    baseline_value = models.FloatField(null=True, blank=True)
    baseline_at = models.DateTimeField(null=True, blank=True)
    goal_met_since = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    scout_config_id = models.UUIDField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    notified_actions = models.JSONField(default=list, blank=True)
    reconcile_after = models.DateTimeField(null=True, blank=True)
    lease = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)

    @property
    def repos(self) -> list[str]:
        return self.repositories or [self.repository]

    class Meta(BetsModel.Meta):
        db_table = "bets_bet"
        constraints = [models.UniqueConstraint(fields=["team_id", "reference"], name="bets_bet_reference")]
        indexes = [models.Index(fields=["team_id", "status"], name="bets_bet_status")]


class WorkItem(BetsModel):
    bet = models.ForeignKey(Bet, on_delete=models.CASCADE, related_name="work_items")
    kind = models.CharField(max_length=16, choices=WorkKind.choices)
    stage = models.CharField(max_length=16, choices=WorkStage.choices, default=WorkStage.WORKING)
    key = models.CharField(max_length=255)
    goal_version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    report_id = models.UUIDField(null=True, blank=True)
    task_id = models.UUIDField(null=True, blank=True)
    task_run_id = models.UUIDField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    pr_url = models.URLField(max_length=500, blank=True, default="")
    flag_key = models.CharField(max_length=200, blank=True, default="")
    experiment_id = models.BigIntegerField(null=True, blank=True)
    merged_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=16, choices=IdeaSource.choices, default=IdeaSource.SCOUT)
    assessment = models.CharField(max_length=16, choices=IdeaAssessment.choices, blank=True, default="")
    evidence = models.JSONField(default=list, blank=True)
    chosen_at = models.DateTimeField(null=True, blank=True)
    chosen_by_id = models.BigIntegerField(null=True, blank=True)
    dismissed_reason = models.TextField(blank=True, default="")
    moves_metric = models.CharField(max_length=255, blank=True, default="")
    plan = models.JSONField(default=dict, blank=True)

    class Meta(BetsModel.Meta):
        db_table = "bets_work_item"
        constraints = [models.UniqueConstraint(fields=["bet", "key"], name="bets_work_key")]
        indexes = [models.Index(fields=["team_id", "task_id"], name="bets_work_task")]


class LedgerEntry(BetsModel):
    bet = models.ForeignKey(Bet, on_delete=models.PROTECT, related_name="ledger")
    work_item = models.ForeignKey(WorkItem, on_delete=models.PROTECT, null=True, blank=True, related_name="ledger")
    kind = models.CharField(max_length=16, choices=LedgerKind.choices)
    amount_cents = models.PositiveBigIntegerField()
    key = models.CharField(max_length=255)
    actor_id = models.BigIntegerField(null=True, blank=True)
    source_ref = models.CharField(max_length=255, blank=True, default="")

    class Meta(BetsModel.Meta):
        db_table = "bets_ledger_entry"
        constraints = [models.UniqueConstraint(fields=["team_id", "key"], name="bets_ledger_key")]

    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValueError("Budget ledger entries are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        raise ValueError("Budget ledger entries cannot be deleted")
