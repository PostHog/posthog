from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework.response import Response

from posthog.models import OrganizationMembership

from products.bets.backend.db import WRITER_DB
from products.bets.backend.facade.contracts import MeasureSearch, Metric
from products.bets.backend.facade.enums import IdeaOutcome, LedgerKind
from products.bets.backend.logic import measures
from products.bets.backend.logic.ledger import append, settle_usage, totals
from products.bets.backend.logic.loop import reconcile
from products.bets.backend.logic.metrics import unfinished
from products.bets.backend.logic.scout import DISMISS_LIMIT, scout_context, scout_job
from products.bets.backend.logic.spend import reconcile_spend, spend_pending
from products.bets.backend.logic.state import bet_state
from products.bets.backend.logic.verdict import MIN_SAMPLES_PER_VARIANT, verdict
from products.bets.backend.logic.workspace import get_settings
from products.bets.backend.models import Bet, LedgerEntry, WorkItem
from products.tasks.backend.facade.contracts import TaskRunCost

ENOUGH = MIN_SAMPLES_PER_VARIANT


def evidence(
    primary: list[float] | None,
    *,
    significant: bool = True,
    guard: list[float] | None = None,
    days: int = 3,
    exposures: dict | None = None,
) -> dict:
    variant = {"key": "test", "significant": significant, "credible_interval": primary} if primary else {"key": "test"}
    return {
        "start_date": (timezone.now() - timedelta(days=days)).isoformat(),
        "results": {
            "variants": ["control", "test"],
            "exposures": exposures or {"control": ENOUGH, "test": ENOUGH},
            "metric_sample_counts": [{"control": ENOUGH, "test": ENOUGH}],
            "primary_metrics_results": [{"name": "1. Share rate", "variant_results": [variant]}],
            "secondary_metrics_results": [
                {
                    "name": "1. Uploads",
                    "variant_results": [{"key": "test", "credible_interval": guard or [-0.01, 0.01]}],
                }
            ],
        },
    }


class TestVerdict(SimpleTestCase):
    @parameterized.expand(
        [
            ("win", evidence([0.05, 0.2]), "increase", IdeaOutcome.WON),
            ("win_when_lower_is_better", evidence([-0.2, -0.05]), "decrease", IdeaOutcome.WON),
            ("loss", evidence([-0.2, -0.05]), "increase", IdeaOutcome.LOST),
            ("guardrail_harm_beats_a_win", evidence([0.05, 0.2], guard=[-0.3, -0.1]), "increase", IdeaOutcome.HARMED),
            (
                "no_clear_effect_at_the_planned_end",
                evidence([-0.05, 0.2], significant=False),
                "increase",
                IdeaOutcome.FLAT,
            ),
            ("clear_win_before_the_planned_end_waits", evidence([0.05, 0.2], days=1), "increase", None),
            (
                "guardrail_harm_stops_before_the_planned_end",
                evidence([0.05, 0.2], guard=[-0.3, -0.1], days=1),
                "increase",
                IdeaOutcome.HARMED,
            ),
            ("the_clock_starts_at_the_first_exposure", evidence([0.05, 0.2]), "increase", None, 1),
            (
                "uneven_traffic_split_marks_a_broken_test",
                evidence([0.05, 0.2], exposures={"control": 1000, "test": 800}),
                "increase",
                IdeaOutcome.BROKEN,
            ),
            (
                "many_people_in_both_variants_marks_a_broken_test",
                evidence([0.05, 0.2], exposures={"control": 1000, "test": 1000, "$multiple": 400}),
                "increase",
                IdeaOutcome.BROKEN,
            ),
            (
                "normal_noise_in_the_split_still_decides",
                evidence([0.05, 0.2], exposures={"control": 1000, "test": 960}),
                "increase",
                IdeaOutcome.WON,
            ),
        ]
    )
    def test_outcome(
        self, _name: str, data: dict, direction: str, expected: IdeaOutcome | None, exposed_days: int | None = None
    ) -> None:
        guardrails = [{"name": "Uploads", "direction": "increase", "max_regression": 0.05}]
        exposed_at = timezone.now() - timedelta(days=exposed_days) if exposed_days else None
        outcome = verdict(data, direction=direction, guardrails=guardrails, run_days=2, exposed_at=exposed_at).outcome
        assert outcome == expected

    def test_small_samples_never_decide(self) -> None:
        data = evidence([0.05, 0.2])
        data["results"]["metric_sample_counts"] = [{"control": ENOUGH, "test": ENOUGH - 1}]
        assert verdict(data, direction="increase", guardrails=[], run_days=2).outcome is None


class TestMetricPeriods(SimpleTestCase):
    @parameterized.expand(
        [
            ("week_in_progress", date(2026, 10, 25), "week", True),
            ("last_full_week", date(2026, 10, 18), "week", False),
            ("today", date(2026, 10, 28), "day", True),
            ("yesterday", date(2026, 10, 27), "day", False),
            ("month_in_progress", date(2026, 10, 1), "month", True),
            ("last_month", date(2026, 9, 1), "month", False),
        ]
    )
    def test_the_headline_skips_a_period_that_has_not_ended(
        self, _name: str, day: date, period: str, expected: bool
    ) -> None:
        with time_machine.travel(datetime(2026, 10, 28, 12, tzinfo=UTC), tick=False):
            assert unfinished(day, period, "UTC") is expected


@dataclass
class FakeRun:
    id: UUID
    task_id: UUID
    status: str
    created_at: object = field(default_factory=timezone.now)
    error_message: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class FakeWorld:
    def __init__(self) -> None:
        self.runs: dict[UUID, FakeRun] = {}
        self.prs: dict[str, list[SimpleNamespace]] = {}
        self.reports: list[SimpleNamespace] = []
        self.experiments: dict[str, SimpleNamespace] = {}
        self.results: dict = {}
        self.concluded: list[tuple[int, str, str]] = []
        self.metric_values: list[float] = [0.1]
        self.cleanup_task: UUID = uuid4()
        self.created: list[dict] = []
        self.logs = ""

    def create_task_without_run(self, **kwargs: object) -> UUID:
        self.created.append(kwargs)
        return uuid4()

    def run_task(self, task_id: UUID, team_id: int, user_id: int, validated_data: dict) -> SimpleNamespace:
        run = FakeRun(id=uuid4(), task_id=task_id, status="in_progress")
        self.runs[run.id] = run
        return SimpleNamespace(error=None, run_error=None, run_id=run.id)

    def get_task_run(self, run_id: UUID, team_id: int) -> FakeRun | None:
        return self.runs.get(run_id)

    def get_latest_run_by_task(self, task_ids: list[str]) -> dict[str, FakeRun]:
        return {str(run.task_id): run for run in self.runs.values() if str(run.task_id) in task_ids}

    def get_pull_requests_for_tasks(self, team_id: int, task_ids: list) -> dict[str, list[SimpleNamespace]]:
        return {str(task_id): self.prs[str(task_id)] for task_id in task_ids if str(task_id) in self.prs}

    def finish(self, work: WorkItem, *, pr: str = "", flag: str = "") -> None:
        assert work.task_run_id is not None
        self.runs[work.task_run_id].status = "completed"
        if pr:
            self.prs[str(work.task_id)] = [SimpleNamespace(url=pr, state="open")]
        if flag:
            self.experiments[flag] = SimpleNamespace(id=len(self.experiments) + 7)

    def pr_state(self, work: WorkItem, state: str) -> None:
        self.prs[str(work.task_id)][0].state = state


class TestBetLoop(APIBaseTest):
    databases = {"default", "bets_db_writer", "bets_db_reader"}

    def setUp(self) -> None:
        super().setUp()
        OrganizationMembership.objects.filter(user=self.user, organization=self.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )
        self.world = world = FakeWorld()
        tasks = SimpleNamespace(
            create_task_without_run=world.create_task_without_run,
            get_task_by_origin_key=lambda *args: None,
            TaskOriginProduct=SimpleNamespace(BETS="bets"),
            update_task=lambda *args, **kwargs: None,
            run_task=world.run_task,
            get_task_run=world.get_task_run,
            get_latest_run_by_task=world.get_latest_run_by_task,
            get_pull_requests_for_tasks=world.get_pull_requests_for_tasks,
            refresh_pull_requests_for_tasks=lambda *args: None,
            read_task_run_logs=lambda *args: world.logs,
        )
        signals = SimpleNamespace(
            scouts_for_source=lambda *args, **kwargs: [SimpleNamespace(config_id=str(uuid4()))],
            scout_reports_for_source=lambda *args, **kwargs: list(world.reports),
            update_scout_for_source=lambda *args, **kwargs: True,
            run_scout_for_source=lambda *args: None,
            WorkflowScoutRunRejected=RuntimeError,
            ScoutRunRejectionKind=SimpleNamespace(CONFLICT="conflict", THROTTLED="throttled"),
        )
        loop = "products.bets.backend.logic.loop"
        stubs: list[tuple[str, object]] = [
            ("products.bets.backend.logic.access.bets_enabled", True),
            ("products.bets.backend.logic.bets.validate_goal", None),
            (f"{loop}.reconcile_spend", None),
            (f"{loop}.spend_pending", False),
            (f"{loop}.task_run_usage_limited", False),
            (f"{loop}.run_settings", {}),
            (f"{loop}.baseline", SimpleNamespace(ready=True, value=0.1, note="")),
        ]
        for target, value in stubs:
            self.patch(target, return_value=value)
        self.patch(f"{loop}.tasks", new=tasks)
        self.patch(f"{loop}.signals", new=signals)
        self.patch(f"{loop}.cancel_task_run")
        self.patch(
            f"{loop}.experiments.experiment_for_read",
            side_effect=lambda **kwargs: world.experiments.get(kwargs["feature_flag_key"]),
        )
        self.patch(f"{loop}.experiment_evidence", side_effect=lambda **kwargs: world.results)
        self.patch(
            f"{loop}.ship",
            side_effect=lambda **kwargs: world.concluded.append(
                (kwargs["experiment_id"], kwargs["conclusion"], kwargs["variant"])
            ),
        )
        for target in (f"{loop}.metric", "products.bets.backend.logic.bets.metric"):
            self.patch(
                target,
                side_effect=lambda *args, **kwargs: Metric(
                    name="Share rate",
                    values=world.metric_values,
                    dates=[],
                    current=world.metric_values[-1],
                    change=None,
                    message="",
                ),
            )
        get_settings(self.team.id).__class__.objects.for_team(self.team.id).using(WRITER_DB).update(
            budget_cents=100000, min_run_hours=0, goal_confirm_hours=0
        )
        self.patch(f"{loop}.cleanup_task_id", side_effect=lambda **kwargs: world.cleanup_task)

    def patch(self, target: str, **kwargs: Any) -> MagicMock:
        patcher = patch(target, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def create(self, **overrides: object) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/bets/",
            {
                "title": "Make sharing easier",
                "statement": "A one-click share after upload will make more people share.",
                "repository": "posthog/example-app",
                "goal_insight": "abc123",
                "goal_metric": "Share rate after upload",
                "target": "0.3",
                "budget_cents": 20000,
                **overrides,
            },
            format="json",
        )
        assert response.status_code == 201, response.content
        return response.json()

    def tick(self, bet: Bet) -> None:
        Bet.objects.for_team(self.team.id).using(WRITER_DB).filter(id=bet.id).update(lease=None, lease_until=None)
        reconcile(self.team.id, bet.id)
        bet.refresh_from_db(using=WRITER_DB)

    def only(self, bet: Bet, kind: str) -> WorkItem:
        work = (
            WorkItem.objects.for_team(self.team.id)
            .using(WRITER_DB)
            .filter(bet=bet, kind=kind)
            .order_by("-created_at")
            .first()
        )
        assert work is not None
        return work

    def new_report(
        self, title: str = "Share button after upload", summary: str = "Evidence.", status: str = "ready"
    ) -> None:
        self.world.reports.append(
            SimpleNamespace(
                report_id=str(uuid4()),
                status=status,
                filed_at=timezone.now(),
                title=title,
                summary=summary,
            )
        )

    def fresh(self, **overrides: object) -> Bet:
        bet = Bet.objects.for_team(self.team.id).using(WRITER_DB).get(id=self.create(**overrides)["id"])
        self.tick(bet)
        return bet

    def running(self, **overrides: object) -> Bet:
        bet = self.fresh(**overrides)
        self.world.finish(self.only(bet, "tracking"))
        self.tick(bet)
        assert bet.status == "running"
        return bet

    def work(self, bet: Bet, work: WorkItem, action: str, reason: str = "") -> Response:
        return self.client.post(
            f"/api/projects/{self.team.id}/bets/{bet.id}/work/",
            {"work_id": str(work.id), "action": action, "reason": reason},
            format="json",
        )

    def build_next(self, bet: Bet) -> WorkItem:
        self.new_report()
        self.tick(bet)
        idea = self.only(bet, "idea")
        assert idea.stage == "proposed" and idea.task_id is None
        assert self.work(bet, idea, "build").status_code == 200
        self.tick(bet)
        idea.refresh_from_db(using=WRITER_DB)
        return idea

    def ship_idea(self, bet: Bet, results: dict) -> WorkItem:
        idea = self.build_next(bet)
        assert idea.stage == "working" and idea.task_run_id
        self.world.finish(idea, pr="https://github.com/posthog/example-app/pull/9", flag=idea.flag_key)
        self.tick(bet)
        idea.refresh_from_db(using=WRITER_DB)
        assert idea.stage == "review"
        self.world.pr_state(idea, "merged")
        self.world.results = results
        self.tick(bet)
        self.tick(bet)
        with time_machine.travel(timezone.now() + timedelta(days=3)):
            self.tick(bet)
        idea.refresh_from_db(using=WRITER_DB)
        return idea

    def test_bet_walks_from_tracking_to_a_won_idea_and_reaches_its_goal(self) -> None:
        bet = Bet.objects.for_team(self.team.id).using(WRITER_DB).get(id=self.create()["id"])
        self.tick(bet)
        tracking = self.only(bet, "tracking")
        assert tracking.stage == "working" and tracking.task_run_id
        self.world.finish(tracking)
        self.tick(bet)
        assert bet.status == "running" and bet.baseline_value == 0.1
        self.world.metric_values = [0.31, 0.32, 0.33]
        self.tick(bet)
        assert bet.status == "running" and bet.goal_met_since is None
        self.world.metric_values = [0.1]
        idea = self.ship_idea(bet, evidence([0.05, 0.2]))
        assert idea.stage == "done" and idea.result["outcome"] == IdeaOutcome.WON and idea.result["shipped"]
        assert self.world.concluded == [(idea.experiment_id, "won", "test")]
        settle_usage(bet, "scout:run-1:tokens", 300)
        settle_usage(bet, "task:build", 40, work=idea)
        cleanup = self.only(bet, "cleanup")
        assert cleanup.task_id == self.world.cleanup_task and cleanup.stage == "working"
        self.world.metric_values = [0.2, 0.25, 0.5]
        self.tick(bet)
        assert bet.status == "running" and bet.goal_met_since is None
        self.world.metric_values = [0.31, 0.32, 0.33]
        self.tick(bet)
        assert bet.status == "reached"
        cleanup.refresh_from_db(using=WRITER_DB)
        assert cleanup.stage == "dropped"
        assert totals(self.team.id, bet).available_cents == 0
        self.world.metric_values = [0.9]
        results = self.client.get(f"/api/projects/{self.team.id}/bets/{bet.id}/").json()["results"]
        assert (results["recorded"], results["final_value"], results["values"]) == (True, 0.33, [0.31, 0.32, 0.33])
        assert results["met_at_start"] is False and results["reached_at"] is not None
        [tried] = results["ideas"]
        assert (tried["outcome"], tried["shipped"], tried["effect"], tried["spent_cents"]) == (
            "won",
            True,
            [0.05, 0.2],
            40,
        )
        assert (tried["learning"], tried["weak_evidence"]) == ("", True)
        assert results["spend"] == {
            "scout_cents": 300,
            "scout_runs": 1,
            "ideas_cents": 40,
            "tracking_cents": 0,
            "returned_cents": results["spend"]["returned_cents"],
            "tested_ideas": 1,
            "per_tested_idea_cents": 340,
        }
        assert results["spend"]["returned_cents"] > 0

    def described(self) -> Bet:
        self.patch("products.bets.backend.logic.loop.validate_goal")
        repositories = ["posthog/example-app", "posthog/example-docs"]
        bet = self.fresh(
            goal_insight="", goal_description="Share rate after upload", target=None, repositories=repositories
        )
        assert self.world.created[-1]["repositories"] == repositories
        self.world.finish(self.only(bet, "tracking"))
        self.tick(bet)
        assert bet.goal_insight == "" and self.only(bet, "tracking").stage == "working"
        self.tick(bet)
        self.world.logs = '{"text": "Tracking is correct.\\nInsight: abc12345"}'
        self.world.finish(self.only(bet, "tracking"))
        self.tick(bet)
        assert bet.goal_insight == "abc12345" and bet.status == "setting_up"
        return bet

    def stuck(self) -> Bet:
        bet = self.running()
        self.build_next(bet)
        for _ in range(4):
            self.tick(bet)
            idea = self.only(bet, "idea")
            if idea.task_run_id:
                self.world.finish(idea)
        self.tick(bet)
        assert self.only(bet, "idea").stage == "stuck"
        return bet

    def reviewing(self) -> tuple[Bet, WorkItem]:
        bet = self.running()
        idea = self.build_next(bet)
        self.world.finish(idea, pr="https://github.com/posthog/example-app/pull/9", flag=idea.flag_key)
        self.tick(bet)
        return bet, idea

    def drive(self, name: str) -> Bet:
        if name == "setting_up":
            return self.fresh()
        if name == "checking_measure":
            return self.described()
        if name == "setting_up_without_budget":
            return self.fresh(budget_cents=0)
        if name in ("finding_ideas", "checking_ideas"):
            return self.running(ideas=["Show upload progress"] if name == "checking_ideas" else [])
        if name == "choosing":
            bet = self.running()
            self.new_report()
            self.tick(bet)
            return bet
        if name == "building":
            bet = self.running()
            self.build_next(bet)
            return bet
        if name in ("reviewing", "testing"):
            bet, idea = self.reviewing()
            if name == "testing":
                self.world.pr_state(idea, "merged")
                self.world.results = evidence([0.05, 0.2], days=1)
                self.tick(bet)
            return bet
        if name == "target_met":
            self.patch(
                "products.bets.backend.logic.loop.baseline",
                return_value=SimpleNamespace(ready=True, value=0.4, note=""),
            )
            return self.running()
        if name in ("confirming_goal", "reached"):
            if name == "confirming_goal":
                get_settings(self.team.id).__class__.objects.for_team(self.team.id).using(WRITER_DB).update(
                    goal_confirm_hours=72
                )
            bet = self.running()
            self.ship_idea(bet, evidence([0.05, 0.2]))
            for work in WorkItem.objects.for_team(self.team.id).using(WRITER_DB).filter(bet=bet):
                if held := totals(self.team.id, work=work).reserved_cents:
                    append(get_settings(self.team.id), bet, LedgerKind.RELEASE, held, f"settled:{work.id}", work=work)
            self.world.metric_values = [0.31, 0.32, 0.33]
            self.tick(bet)
            return bet
        if name == "stuck":
            return self.stuck()
        if name == "dismissed":
            bet = self.running()
            for number in range(DISMISS_LIMIT):
                self.new_report(f"Idea {number}")
                self.tick(bet)
                proposed = WorkItem.objects.for_team(self.team.id).using(WRITER_DB).get(bet=bet, stage="proposed")
                assert self.work(bet, proposed, "dismiss", "Not for now").status_code == 200
            return bet
        bet = self.running()
        if name == "paused":
            self.client.post(f"/api/projects/{self.team.id}/bets/{bet.id}/status/", {"status": "paused"}, format="json")
        else:
            append(
                get_settings(self.team.id),
                bet,
                LedgerKind.DEALLOCATE,
                totals(self.team.id, bet).available_cents,
                "drain",
            )
            self.tick(bet)
        return bet

    def state(self, bet: Bet) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/bets/{bet.id}/")
        assert response.status_code == 200, response.content
        return response.json()["state"]

    @parameterized.expand(
        [
            ("setting_up", "setting_up", "Checking how the goal is measured", None, False),
            ("checking_measure", "checking_measure", "Set the target to start", "edit", True),
            ("setting_up_without_budget", "waiting", "The budget is used up", "budget", True),
            ("finding_ideas", "finding_ideas", "Finding ideas", None, False),
            ("checking_ideas", "checking_ideas", "Checking your ideas", None, False),
            ("choosing", "choosing", "Choose an idea to build", "ideas", True),
            ("building", "building", "Building an idea", None, False),
            ("reviewing", "reviewing", "Review the pull request", "pull_request", True),
            ("testing", "testing", "Testing an idea", None, False),
            ("confirming_goal", "confirming_goal", "The goal is at the target", None, False),
            ("target_met", "waiting", "The goal already meets the target", "edit", True),
            ("stuck", "waiting", "Building stopped", "work", True),
            ("dismissed", "waiting", f"You dismissed the last {DISMISS_LIMIT} ideas", "ideas", True),
            ("paused", "paused", "The bet is paused", None, False),
            ("reached", "ended", f"Goal reached on {timezone.now():%b} {timezone.now().day}", None, True),
            ("spent", "ended", "Budget used. The goal was not reached.", None, True),
        ]
    )
    def test_bet_state_names_one_phase_and_one_owner_action(
        self, name: str, phase: str, headline: str, kind: str | None, needs_you: bool
    ) -> None:
        state = self.state(self.drive(name))
        assert (state["phase"], state["headline"], (state["action"] or {}).get("kind"), state["needs_you"]) == (
            phase,
            headline,
            kind,
            needs_you,
        ), state

    @parameterized.expand(
        [
            ("create_increase", None, {"target": "0.05"}),
            ("create_decrease", None, {"target": "0.2", "direction": "decrease"}),
            ("edit_target", {"target": "0.05"}, {}),
        ]
    )
    def test_a_target_the_goal_already_meets_is_refused(self, _name: str, edit: dict | None, create: dict) -> None:
        if edit is None:
            response = self.client.post(
                f"/api/projects/{self.team.id}/bets/",
                {
                    "title": "Met",
                    "statement": "Already there.",
                    "repository": "posthog/example-app",
                    "goal_insight": "abc123",
                    "goal_metric": "Share rate after upload",
                    "budget_cents": 1000,
                    **create,
                },
                format="json",
            )
        else:
            bet = self.create()
            response = self.client.patch(f"/api/projects/{self.team.id}/bets/{bet['id']}/", edit, format="json")
        assert response.status_code == 400 and "already" in str(response.json()), response.content

    def test_raising_the_target_of_a_reached_bet_keeps_the_goal_and_asks_for_budget(self) -> None:
        bet = self.drive("reached")
        assert bet.status == "reached" and bet.goal_met_since is not None
        response = self.client.patch(f"/api/projects/{self.team.id}/bets/{bet.id}/", {"target": "0.5"}, format="json")
        assert response.status_code == 200, response.content
        bet.refresh_from_db(using=WRITER_DB)
        assert (bet.status, bet.goal_version, bet.goal_met_since is None) == ("running", 1, True)
        assert WorkItem.objects.for_team(self.team.id).using(WRITER_DB).filter(bet=bet, kind="tracking").count() == 1
        assert (response.json()["state"]["action"] or {}).get("kind") == "budget"

    def test_described_goal_gets_its_insight_from_tracking_and_waits_for_the_target(self) -> None:
        bet = self.described()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/bets/{bet.id}/", {"goal_insight": "abc12345", "target": "0.4"}, format="json"
        )
        assert response.status_code == 200, response.content
        self.tick(bet)
        assert bet.status == "running" and bet.goal_version == 1

    def test_losing_ideas_ship_control_and_the_bet_keeps_going(self) -> None:
        bet = self.running()
        for _ in range(3):
            assert self.ship_idea(bet, evidence([-0.2, -0.05])).result["outcome"] == IdeaOutcome.LOST
        self.tick(bet)
        assert bet.status == "running"
        assert {variant for _, _, variant in self.world.concluded} == {"control"}

    def test_scout_ideas_wait_for_the_owner_and_only_one_is_built_at_a_time(self) -> None:
        bet = self.running()
        self.new_report(
            "Bet idea: instant uploads",
            "Most stop after one file ([funnel](http://localhost/project/1/insights/abc)). "
            "[Replay 0:42](http://localhost/project/1/replay/xyz?t=42) shows a disabled button.",
        )
        self.new_report("Bet idea: add more files after a share")
        with patch("products.bets.backend.logic.notify.create_notification") as notify:
            self.tick(bet)
            self.tick(bet)
        assert [call.args[0].title for call in notify.call_args_list] == [f"{bet.title}: Choose an idea to build"]
        ideas = list(WorkItem.objects.for_team(self.team.id).using(WRITER_DB).filter(bet=bet, kind="idea"))
        assert {idea.stage for idea in ideas} == {"proposed"} and all(idea.task_id is None for idea in ideas)
        first = next(idea for idea in ideas if idea.title == "Instant uploads")
        assert [item["kind"] for item in first.evidence] == ["insight", "replay"]
        assert self.work(bet, first, "build").status_code == 200
        second = next(idea for idea in ideas if idea.id != first.id)
        assert self.work(bet, second, "build").status_code == 400
        first.refresh_from_db(using=WRITER_DB)
        assert first.stage == "working" and first.flag_key == f"bet-{bet.reference}-1"
        changed = self.client.patch(
            f"/api/projects/{self.team.id}/bets/{bet.id}/", {"goal_insight": "def45678"}, format="json"
        )
        assert changed.status_code == 200
        self.tick(bet)
        self.world.finish(self.only(bet, "tracking"))
        self.tick(bet)
        assert bet.status == "running" and bet.goal_version == 2
        self.new_report("Bet idea: show upload progress")
        self.tick(bet)
        after_change = self.only(bet, "idea")
        assert self.work(bet, after_change, "build").status_code == 200
        after_change.refresh_from_db(using=WRITER_DB)
        assert after_change.flag_key == f"bet-{bet.reference}-2"

    @parameterized.expand(
        [
            ("not_supported", "Not supported. Uploads finish in 2 s.", "ready", "not_supported"),
            ("supported", "**Supported.** People wait for the upload.", "ready", "supported"),
            ("no_marker", "People wait for the upload.", "ready", "pending"),
            ("needs_owner_input", "Not supported. Uploads finish in 2 s.", "pending_input", "not_supported"),
            ("suppressed_by_the_inbox", "Not supported. Uploads finish in 2 s.", "suppressed", "not_supported"),
        ]
    )
    def test_owner_idea_gets_the_scout_check(self, _name: str, summary: str, status: str, expected: str) -> None:
        bet = self.running(ideas=["Show upload progress as a percent"])
        owner = WorkItem.objects.for_team(self.team.id).using(WRITER_DB).get(bet=bet, source="owner")
        assert owner.stage == "proposed" and owner.assessment == "pending"
        assert scout_job(bet).mode == "find"
        assert "Choose an idea to build" not in [item["title"] for item in bet_state(bet).actions]
        self.new_report("Owner idea 1: Show upload progress as a percent", summary, status)
        self.tick(bet)
        owner.refresh_from_db(using=WRITER_DB)
        assert owner.assessment == expected and owner.report_id is not None, owner.assessment
        assert WorkItem.objects.for_team(self.team.id).using(WRITER_DB).filter(bet=bet, kind="idea").count() == 1

    def test_scout_job_follows_the_bet_state(self) -> None:
        bet = self.running()
        assert scout_job(bet).mode == "find"
        self.patch(
            "products.signals.backend.facade.api.empty_scout_run_summaries",
            return_value=["Checked the upload funnel over 31 days.", "Checked paths."],
        )
        [empty] = bet_state(bet).actions
        assert empty["title"] == "The Scout found no new ideas"
        assert "Checked the upload funnel over 31 days." in empty["description"]
        self.new_report()
        self.tick(bet)
        assert scout_job(bet).mode == ""
        assert self.work(bet, self.only(bet, "idea"), "build").status_code == 200
        assert scout_job(bet).mode == ""
        response = self.client.post(
            f"/api/projects/{self.team.id}/bets/{bet.id}/ideas/", {"title": "Copy the link after upload"}, format="json"
        )
        assert response.status_code == 200
        assert scout_job(bet).mode == "check"
        assert "Do not file ideas of your own" in scout_context(self.team.id, f"{bet.id}:v{bet.goal_version}")

    def test_dismiss_needs_a_reason_and_the_scout_reads_it(self) -> None:
        bet = self.running()
        self.new_report()
        self.tick(bet)
        idea = self.only(bet, "idea")
        assert self.work(bet, idea, "dismiss").status_code == 400
        assert self.work(bet, idea, "dismiss", "Too risky for checkout").status_code == 200
        assert "Reason: Too risky for checkout" in scout_context(self.team.id, f"{bet.id}:v{bet.goal_version}")
        for number in range(DISMISS_LIMIT - 1):
            assert scout_job(bet).mode == "find"
            self.new_report(f"Idea {number}")
            self.tick(bet)
            proposed = WorkItem.objects.for_team(self.team.id).using(WRITER_DB).get(bet=bet, stage="proposed")
            assert self.work(bet, proposed, "dismiss", "Not for now").status_code == 200
        assert scout_job(bet).mode == ""
        assert (
            self.client.post(
                f"/api/projects/{self.team.id}/bets/{bet.id}/ideas/",
                {"title": "Copy the link after upload"},
                format="json",
            ).status_code
            == 200
        )
        assert scout_job(bet).mode == "find"

    def test_used_budget_stops_the_bet_and_more_budget_resumes_it(self) -> None:
        bet = self.drive("spent")
        assert bet.status == "spent"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/bets/{bet.id}/",
            {"budget_cents": totals(self.team.id, bet).allocated_cents + 1000},
            format="json",
        )
        assert response.status_code == 200, response.content
        bet.refresh_from_db(using=WRITER_DB)
        assert bet.status == "running"

    def test_closed_pull_request_drops_the_idea_and_frees_the_scout(self) -> None:
        bet = Bet.objects.for_team(self.team.id).using(WRITER_DB).get(id=self.create()["id"])
        self.tick(bet)
        self.world.finish(self.only(bet, "tracking"))
        self.tick(bet)
        idea = self.build_next(bet)
        self.world.finish(idea, pr="https://github.com/posthog/example-app/pull/9", flag=idea.flag_key)
        self.tick(bet)
        self.world.pr_state(idea, "closed")
        self.tick(bet)
        idea.refresh_from_db(using=WRITER_DB)
        assert idea.stage == "dropped" and not self.world.concluded
        assert self.build_next(bet).id != idea.id

    def test_task_that_never_finishes_its_work_gets_stuck_after_three_attempts(self) -> None:
        bet = self.stuck()
        stuck = self.only(bet, "idea")
        self.new_report("Copy the link after upload")
        self.tick(bet)
        assert "Choose an idea to build" not in [item["title"] for item in bet_state(bet).actions]
        assert self.work(bet, stuck, "drop").status_code == 200
        stuck.refresh_from_db(using=WRITER_DB)
        assert stuck.stage == "dropped"
        assert "Choose an idea to build" in [item["title"] for item in bet_state(bet).actions]

    def test_create_retry_keeps_one_bet_and_one_allocation(self) -> None:
        operation_id = str(uuid4())
        assert self.create(operation_id=operation_id)["id"] == self.create(operation_id=operation_id)["id"]
        assert Bet.objects.for_team(self.team.id).using(WRITER_DB).count() == 1
        assert totals(self.team.id).allocated_cents == 20000

    def test_budget_cannot_be_overallocated_and_close_keeps_spend(self) -> None:
        bet = Bet.objects.for_team(self.team.id).using(WRITER_DB).get(id=self.create(budget_cents=80000)["id"])
        response = self.client.post(
            f"/api/projects/{self.team.id}/bets/",
            {
                "title": "Second",
                "statement": "More",
                "repository": "PostHog/x",
                "goal_insight": "def456",
                "goal_metric": "M",
                "target": "1",
                "budget_cents": 30000,
            },
            format="json",
        )
        assert response.status_code == 400
        self.tick(bet)
        work = self.only(bet, "tracking")
        settings = get_settings(self.team.id)
        append(settings, bet, LedgerKind.SPEND, 300, "spend", self.user.id, work)
        append(settings, bet, LedgerKind.SPEND, 300, "spend", self.user.id, work)
        response = self.client.post(
            f"/api/projects/{self.team.id}/bets/{bet.id}/status/", {"status": "closed"}, format="json"
        )
        assert response.status_code == 200, response.content
        assert response.json()["money"] == {
            "allocated_cents": 500,
            "spent_cents": 300,
            "reserved_cents": 200,
            "available_cents": 0,
        }
        assert LedgerEntry.objects.for_team(self.team.id).using(WRITER_DB).filter(key="spend").count() == 1
        work.refresh_from_db(using=WRITER_DB)
        assert work.task_run_id is not None
        self.world.runs[work.task_run_id].status = "completed"
        self.tick(bet)
        money = totals(self.team.id, bet)
        assert (money.allocated_cents, money.reserved_cents, money.spent_cents) == (300, 0, 300)

    def test_usage_settlement_is_idempotent_and_unknown_cost_stays_pending(self) -> None:
        bet = Bet.objects.for_team(self.team.id).using(WRITER_DB).get(id=self.create()["id"])
        self.tick(bet)
        work = self.only(bet, "tracking")
        with (
            patch(
                "products.bets.backend.logic.spend.tasks.get_latest_run_by_task",
                return_value={str(work.task_id): object()},
            ),
            patch("products.bets.backend.logic.spend.signals.scout_run_ids_for_source", return_value=[]),
        ):
            with patch(
                "products.bets.backend.logic.spend.get_task_cost",
                return_value=TaskRunCost(token_cost=120, compute_cost=None),
            ):
                reconcile_spend(bet)
                reconcile_spend(bet)
                assert spend_pending(bet)
                assert totals(self.team.id, bet).spent_cents == 120
            with patch(
                "products.bets.backend.logic.spend.get_task_cost",
                return_value=TaskRunCost(token_cost=170, compute_cost=30),
            ):
                reconcile_spend(bet)
                assert not spend_pending(bet)
        assert totals(self.team.id, bet).spent_cents == 200


class TestMeasureOptions(SimpleTestCase):
    def run_options(self, goal: str, model: Any) -> tuple[MeasureSearch, MagicMock]:
        saved = [
            SimpleNamespace(
                short_id="share001",
                name="Share rate",
                query={
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "shared_file", "math": "dau"}],
                },
            ),
            SimpleNamespace(
                short_id="upload01",
                name="Uploads",
                query={"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "uploaded_file"}]},
            ),
        ]
        create = MagicMock()
        with (
            patch.object(measures, "saved_insights_for_read", return_value=saved),
            patch.object(measures, "top_events", return_value=["shared_file", "uploaded_file"]),
            patch.object(measures, "wait_days", return_value={}),
            patch.object(measures, "refresh_metrics"),
            patch.object(
                measures,
                "metric",
                return_value=Metric(
                    name="Measure", values=[1.0], dates=["2026-10-01"], current=1.0, change=None, message=""
                ),
            ),
            patch.object(measures, "proposed_plan", return_value=None),
            patch.object(measures, "project_id", return_value=1),
            patch.object(measures, "get_settings", return_value=SimpleNamespace(mde_percent=10, min_run_hours=72)),
            patch.object(measures, "get_or_create_saved_insight", create),
            patch.object(measures, "complete", side_effect=model),
        ):
            return measures.measure_options(
                SimpleNamespace(id=1, project_id=1, parent_team=None), SimpleNamespace(id=1), goal
            ), create

    def test_only_checked_measures_reach_the_owner(self) -> None:
        def model(team: Any, system: str, content: str) -> dict:
            if system == measures.PROMPT:
                return {
                    "draft": "Share of new uploaders who share a file within a day.",
                    "options": [
                        {"insight": "share001", "why": "a"},
                        {"insight": "upload01", "why": "b"},
                        {"new": {"name": "Dub rate", "kind": "users", "event": "published_dub"}, "why": "c"},
                        {"new": {"name": "Sharers", "kind": "users", "event": "shared_file"}, "why": "d"},
                    ],
                }
            return {
                "checks": [
                    {"id": "share001", "verdict": "fits"},
                    {"id": "upload01", "verdict": "no"},
                    {"id": "new2", "verdict": "no"},
                ]
            }

        search, create = self.run_options("More uploaders share a file", model)

        assert [option.insight for option in search.options] == ["share001"]
        assert search.draft == "Share of new uploaders who share a file within a day."
        create.assert_not_called()

    def test_a_model_outage_returns_no_options(self) -> None:
        def model(team: Any, system: str, content: str) -> dict:
            raise measures.MeasureModelUnavailable

        search, create = self.run_options("More uploaders download a file", model)

        assert search.options == []
        create.assert_not_called()
