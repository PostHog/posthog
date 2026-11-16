from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from temporalio.service import RPCError, RPCStatusCode

from posthog.hogql.database.models import SavedQuery

from posthog.models.team import Team

from products.data_catalog.backend.facade.contracts import (
    AdjustedRun,
    ChartSource,
    MetricRunCounts,
    ProposedMetric,
    SectionFailure,
    TableSource,
    TopicDefinition,
    UncoveredGroup,
    UsageSnapshotPayload,
)
from products.data_catalog.backend.facade.enums import JudgeRelation, ShapeOutcome, UsageSection, UsageSnapshotStatus
from products.data_catalog.backend.logic.metrics import upsert_metric
from products.data_catalog.backend.logic.usage_scan import (
    SCAN_START_FAILED_MESSAGE,
    create_usage_snapshot,
    finalize_usage_snapshot,
    teams_due_for_scan,
)
from products.data_catalog.backend.logic.usage_snapshots import (
    SCAN_STOPPED_MESSAGE,
    STALE_COMPUTING,
    UsageReader,
    _denied_tables_and_views,
    _viewable_charts,
    payload_to_json,
    visible_payload,
)
from products.data_catalog.backend.models import Metric, UsageSnapshot

_SNAPSHOTS = "products.data_catalog.backend.logic.usage_snapshots"
_FLAG = "products.data_catalog.backend.logic.usage_snapshots.posthoganalytics.feature_enabled"
_VIEWABLE = "products.data_catalog.backend.logic.usage_snapshots.viewable_insight_definitions"
_SCAN = "products.data_catalog.backend.logic.usage_scan"
_TEMPORAL = f"{_SCAN}.sync_connect"
_WINDOW_END = datetime(2026, 10, 26, tzinfo=UTC)


def _adjusted(metric_id: UUID, *, is_scout: bool = False, sql: str = "select count() from events") -> AdjustedRun:
    return AdjustedRun(
        metric_id=metric_id,
        read_metric_first=False,
        relation=JudgeRelation.SERVES,
        intent="weekly signups",
        sql=sql,
        reasoning="Same event and aggregate.",
        occurred_at=_WINDOW_END - timedelta(days=1),
        session_id=None,
        is_scout=is_scout,
    )


_VISIBLE = UUID("00000000-0000-0000-0000-000000000001")
_HIDDEN = UUID("00000000-0000-0000-0000-000000000002")


def _group(sql: str, matched: UUID | None = None) -> UncoveredGroup:
    return UncoveredGroup(
        fingerprint_digest=sql,
        measure=sql,
        outcome=ShapeOutcome.SLICE if matched else ShapeOutcome.UNCOVERED,
        matched_metric_id=matched,
        distinct_people=2,
        built=1,
        sample_sql=sql,
        draft_name=None,
        draft_description=None,
    )


def _proposal(
    definition: str,
    charts: list[ChartSource] | None = None,
    *,
    digests: list[str] | None = None,
    other_charts: int = 0,
) -> ProposedMetric:
    return ProposedMetric(
        name="revenue",
        description="Revenue.",
        definition=definition,
        measures=1,
        people=2,
        built=1,
        charts=charts or [],
        other_charts=other_charts,
        surfaces=[],
        agents=None,
        fingerprint_digests=digests or [],
    )


def _counts(metric_id: UUID) -> MetricRunCounts:
    return MetricRunCounts(metric_id=metric_id, direct_runs={"web": 1}, direct_people=1, scout_runs=0)


class TestVisiblePayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_denied_tables_keeps_every_query", frozenset(), "select sum(amount) from billing", True),
            ("query_over_a_denied_table", frozenset({"billing"}), "select sum(amount) from billing", False),
            ("query_over_another_table", frozenset({"billing"}), "select count() from events", True),
            ("call_of_a_denied_view", frozenset({"revenue_view"}), "select * from revenue_view()", False),
            ("unparseable_query_with_denied_tables", frozenset({"billing"}), "select count( from", False),
            (
                "cut_query_with_denied_tables",
                frozenset({"billing"}),
                "select count() from events where " + "x = 1 and " * 600 + "1",
                False,
            ),
        ]
    )
    def test_reader_sees_only_visible_metrics_and_allowed_sql(
        self, _name: str, denied: frozenset[str], sql: str, kept: bool
    ) -> None:
        payload = UsageSnapshotPayload(
            metric_runs=[_counts(_VISIBLE), _counts(_HIDDEN)],
            adjusted_runs=[_adjusted(_VISIBLE, sql=sql), _adjusted(_HIDDEN)],
        )

        visible = visible_payload(payload, UsageReader(visible_metric_ids=frozenset({_VISIBLE}), denied_tables=denied))

        assert [counts.metric_id for counts in visible.metric_runs or []] == [_VISIBLE]
        assert [run.metric_id for run in visible.adjusted_runs or []] == ([_VISIBLE] if kept else [])

    def test_reader_does_not_see_a_source_over_a_denied_table(self) -> None:
        payload = UsageSnapshotPayload(
            table_sources=[
                TableSource(name="billing", sessions=3, people=2),
                TableSource(name="revenue_daily", sessions=2, people=1),
            ]
        )

        visible = visible_payload(
            payload, UsageReader(visible_metric_ids=frozenset(), denied_tables=frozenset({"billing"}))
        )

        assert [source.name for source in visible.table_sources or []] == ["revenue_daily"]

    @parameterized.expand([("open_reader", frozenset(), 1), ("reader_with_a_denied_table", frozenset({"billing"}), 0)])
    def test_topic_titles_reach_only_readers_without_denied_tables(
        self, _name: str, denied: frozenset[str], kept: int
    ) -> None:
        payload = UsageSnapshotPayload(topic_definitions=[TopicDefinition(title="Payroll", description="Salaries.")])

        visible = visible_payload(payload, UsageReader(visible_metric_ids=frozenset(), denied_tables=denied))

        assert len(visible.topic_definitions or []) == kept

    def test_reader_does_not_see_measures_or_proposals_over_denied_tables_or_hidden_metrics(self) -> None:
        payload = UsageSnapshotPayload(
            uncovered=[
                _group("select sum(amount) from billing"),
                _group("select count() from events", matched=_HIDDEN),
                _group("select count() from events", matched=_VISIBLE),
                _group("select count() from events where " + "x = 1 and " * 200 + "1", matched=_VISIBLE),
            ],
            proposed_metrics=[
                _proposal("select sum(amount) from billing", digests=["select sum(amount) from billing"]),
                _proposal("select count() from events", digests=["select count() from events"]),
                # The draft names no denied table, but the measure it drafts from reads one.
                _proposal("select count() from invoices", digests=["select sum(amount) from billing"]),
                # A proposal with no measures, or a measure the payload does not hold, cannot be checked.
                _proposal("select count() from events", digests=[]),
                _proposal("select count() from events", digests=["select avg(amount) from events"]),
            ],
        )

        visible = visible_payload(
            payload, UsageReader(visible_metric_ids=frozenset({_VISIBLE}), denied_tables=frozenset({"billing"}))
        )

        assert [group.matched_metric_id for group in visible.uncovered or []] == [_VISIBLE]
        assert [proposal.definition for proposal in visible.proposed_metrics or []] == ["select count() from events"]


class TestViewableCharts(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_dashboard_access", False, set(), None),
            ("dashboard_hidden_by_its_own_rule", True, set(), None),
            ("dashboard_the_reader_may_open", True, {7}, "Growth"),
        ]
    )
    def test_reader_sees_only_charts_and_dashboards_they_may_open(
        self, _name: str, sees_dashboards: bool, viewable_dashboards: set[int], dashboard_name: str | None
    ) -> None:
        access = MagicMock()
        access.check_access_level_for_resource.return_value = sees_dashboards
        charts = [
            ChartSource(
                insight_short_id=short_id, insight_name=short_id, dashboard_id=7, dashboard_name="Growth", people=3
            )
            for short_id in ("allowed", "blocked")
        ]
        reader = UsageReader(
            visible_metric_ids=frozenset(),
            denied_tables=frozenset(),
            team=MagicMock(),
            user=MagicMock(),
            user_access_control=access,
        )

        with (
            patch(_VIEWABLE, return_value={"allowed": MagicMock()}),
            patch(f"{_SNAPSHOTS}.viewable_dashboard_ids", return_value=viewable_dashboards),
        ):
            visible = _viewable_charts(
                UsageSnapshotPayload(proposed_metrics=[_proposal("select count() from events", charts)]), reader
            )

        assert [
            (chart.insight_short_id, chart.dashboard_name) for chart in (visible.proposed_metrics or [])[0].charts
        ] == [("allowed", dashboard_name)]

    def test_charts_the_reader_may_not_open_leave_their_places_to_the_next_ones(self) -> None:
        access = MagicMock()
        access.check_access_level_for_resource.return_value = False
        charts = [
            ChartSource(
                insight_short_id=short_id, insight_name=short_id, dashboard_id=None, dashboard_name=None, people=3
            )
            for short_id in [f"blocked{index}" for index in range(6)] + [f"allowed{index}" for index in range(7)]
        ]
        reader = UsageReader(
            visible_metric_ids=frozenset(),
            denied_tables=frozenset(),
            team=MagicMock(),
            user=MagicMock(),
            user_access_control=access,
        )

        with (
            patch(_VIEWABLE, return_value={f"allowed{index}": MagicMock() for index in range(7)}),
            patch(f"{_SNAPSHOTS}.viewable_dashboard_ids", return_value=set()),
        ):
            visible = _viewable_charts(
                UsageSnapshotPayload(
                    proposed_metrics=[_proposal("select count() from events", charts, other_charts=3)]
                ),
                reader,
            )

        [proposal] = visible.proposed_metrics or []
        assert [chart.insight_short_id for chart in proposal.charts] == [f"allowed{index}" for index in range(5)]
        # Two allowed charts past the shown ones, and the three the scan did not store.
        assert proposal.other_charts == 5


class TestDeniedViews(SimpleTestCase):
    @parameterized.expand(
        [
            ("same_name", "select * from revenue_view"),
            ("qualified_name_in_another_case", "select * from models.Revenue_View"),
            ("call_of_the_view", "select * from revenue_view()"),
        ]
    )
    def test_a_view_over_a_denied_table_is_denied_directly_or_through_another_view(
        self, _name: str, rollup_sql: str
    ) -> None:
        views = {
            "revenue_view": "select sum(amount) from billing",
            "revenue_rollup": rollup_sql,
            "events_view": "select count() from events",
        }
        database = MagicMock(_denied_tables={"billing"})
        database.get_view_names.return_value = list(views)
        database.get_table.side_effect = lambda name: SavedQuery(id=name, name=name, query=views[name], fields={})

        with patch(f"{_SNAPSHOTS}.Database.create_for", return_value=database):
            denied = _denied_tables_and_views(MagicMock(), MagicMock(), MagicMock())

        assert denied == {"billing", "revenue_view", "revenue_rollup"}


class TestUsageSnapshotAPI(APIBaseTest):
    def _snapshot(
        self,
        *,
        team: Team | None = None,
        snapshot_status: UsageSnapshotStatus = UsageSnapshotStatus.DONE,
        computed_at: datetime | None = _WINDOW_END,
        payload: UsageSnapshotPayload | None = None,
    ) -> UsageSnapshot:
        team = team or self.team
        return UsageSnapshot.objects.for_team(team.id).create(
            team=team,
            status=snapshot_status.value,
            window_start=_WINDOW_END - timedelta(days=28),
            window_end=_WINDOW_END,
            computed_at=computed_at,
            payload=payload_to_json(payload or UsageSnapshotPayload()),
        )

    @parameterized.expand([("latest", "data_catalog/usage/latest/"), ("metric", "data_catalog/metrics/mrr/usage/")])
    def test_usage_endpoints_404_while_flag_is_off(self, _name: str, path: str) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        self._snapshot()
        with patch(_FLAG, return_value=False):
            response = self.client.get(f"/api/projects/{self.team.id}/{path}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_latest_returns_newest_finished_snapshot_of_the_team(self) -> None:
        url = f"/api/projects/{self.team.id}/data_catalog/usage/latest/"
        with patch(_FLAG, return_value=True):
            assert self.client.get(url).status_code == status.HTTP_404_NOT_FOUND

            self._snapshot(computed_at=_WINDOW_END - timedelta(days=7))
            newest = self._snapshot()
            self._snapshot(snapshot_status=UsageSnapshotStatus.COMPUTING, computed_at=None)
            self._snapshot(snapshot_status=UsageSnapshotStatus.ERROR, computed_at=_WINDOW_END + timedelta(days=1))
            other_team = Team.objects.create(organization=self.organization, name="Other")
            self._snapshot(team=other_team, computed_at=_WINDOW_END + timedelta(days=2))

            response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["id"] == str(newest.id)
        assert response.json()["payload"]["metric_runs"] is None

    def test_metric_usage_returns_only_that_metrics_slice(self) -> None:
        mrr = upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        arr = upsert_metric(team=self.team, user=self.user, name="arr", description="Annual revenue")
        self._snapshot(
            payload=UsageSnapshotPayload(
                metric_runs=[
                    MetricRunCounts(
                        metric_id=mrr.id,
                        direct_runs={"web": 3, "mcp": 5},
                        direct_people=4,
                        scout_runs=120,
                    ),
                    MetricRunCounts(
                        metric_id=arr.id,
                        direct_runs={"web": 9},
                        direct_people=1,
                        scout_runs=0,
                    ),
                ],
                adjusted_runs=[
                    _adjusted(mrr.id),
                    _adjusted(mrr.id, is_scout=True),
                    _adjusted(arr.id),
                ],
            )
        )

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["runs"]["direct_runs"] == {"web": 3, "mcp": 5}
        assert body["runs"]["scout_runs"] == 120
        assert [(run["metric_id"], run["is_scout"]) for run in body["adjusted_runs"]] == [
            (str(mrr.id), False),
            (str(mrr.id), True),
        ]

    @parameterized.expand(
        [
            ("running_scan", timedelta(hours=1), "computing", ""),
            ("dead_scan", STALE_COMPUTING + timedelta(hours=1), "error", SCAN_STOPPED_MESSAGE),
        ]
    )
    def test_list_reports_a_computing_row_past_the_scan_timeout_as_error(
        self, _name: str, age: timedelta, expected_status: str, expected_message: str
    ) -> None:
        row = self._snapshot(snapshot_status=UsageSnapshotStatus.COMPUTING, computed_at=None)
        UsageSnapshot.objects.for_team(self.team.id).filter(id=row.id).update(created_at=timezone.now() - age)

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [(scan["status"], scan["error_message"]) for scan in response.json()] == [
            (expected_status, expected_message)
        ]

    @parameterized.expand(
        [("denied_table", "billing", status.HTTP_404_NOT_FOUND), ("allowed_table", "events", status.HTTP_200_OK)]
    )
    @patch("products.data_catalog.backend.logic.metrics.Database.create_for")
    def test_metric_usage_404s_for_a_metric_over_a_denied_table(
        self, _name: str, table: str, expected_status: int, create_database: MagicMock
    ) -> None:
        create_database.return_value = MagicMock(_denied_tables={"billing"})
        mrr = upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        Metric.objects.for_team(self.team.id).filter(pk=mrr.id).update(referenced_table_names=[table])
        self._snapshot(payload=UsageSnapshotPayload(metric_runs=[_counts(mrr.id)]))

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == expected_status, response.json()

    def test_a_partly_failed_scan_is_done_and_names_only_the_failures_a_metric_reads(self) -> None:
        upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        snapshot = self._snapshot(snapshot_status=UsageSnapshotStatus.COMPUTING, computed_at=None)
        finalize_usage_snapshot(
            self.team.id,
            snapshot.id,
            failed_sections=[
                SectionFailure(section=UsageSection.ADJUSTED_RUNS, reason="The judge timed out."),
                SectionFailure(section=UsageSection.TOPICS, reason="The embedding service is down."),
            ],
        )

        with patch(_FLAG, return_value=True):
            response = self.client.get(f"/api/projects/{self.team.id}/data_catalog/metrics/mrr/usage/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["failed_sections"] == [{"section": "adjusted_runs", "reason": "The judge timed out."}]

    @parameterized.expand(
        [
            ("no_scan_running", None, timedelta(0), True, status.HTTP_202_ACCEPTED),
            ("scan_running", UsageSnapshotStatus.COMPUTING, timedelta(hours=1), True, status.HTTP_409_CONFLICT),
            ("dead_scan", UsageSnapshotStatus.COMPUTING, timedelta(hours=20), True, status.HTTP_202_ACCEPTED),
            (
                "scan_in_the_last_hour",
                UsageSnapshotStatus.DONE,
                timedelta(minutes=30),
                True,
                status.HTTP_429_TOO_MANY_REQUESTS,
            ),
            ("scan_over_an_hour_ago", UsageSnapshotStatus.DONE, timedelta(hours=2), True, status.HTTP_202_ACCEPTED),
            ("no_ai_consent", None, timedelta(0), False, status.HTTP_403_FORBIDDEN),
            (
                "scan_that_never_started_in_the_last_hour",
                UsageSnapshotStatus.ERROR,
                timedelta(minutes=30),
                True,
                status.HTTP_202_ACCEPTED,
                SCAN_START_FAILED_MESSAGE,
            ),
        ]
    )
    @time_machine.travel("2026-10-26T12:00:00Z", tick=False)
    def test_recompute_starts_one_scan_at_a_time(
        self,
        _name: str,
        existing_status: UsageSnapshotStatus | None,
        existing_age: timedelta,
        ai_approved: bool,
        expected_status: int,
        existing_error: str = "",
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()
        if existing_status is not None:
            existing = self._snapshot(snapshot_status=existing_status, computed_at=None)
            UsageSnapshot.objects.for_team(self.team.id).filter(id=existing.id).update(
                created_at=datetime(2026, 10, 26, 12, 0, tzinfo=UTC) - existing_age, error_message=existing_error
            )
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()

        with patch(_FLAG, return_value=True), patch(_TEMPORAL, return_value=temporal):
            response = self.client.post(f"/api/projects/{self.team.id}/data_catalog/usage/recompute/")

        assert response.status_code == expected_status, response.json()
        started = expected_status == status.HTTP_202_ACCEPTED
        assert temporal.start_workflow.await_count == (1 if started else 0)
        assert UsageSnapshot.objects.for_team(self.team.id).count() == (1 if existing_status else 0) + started
        if started:
            assert response.json()["status"] == UsageSnapshotStatus.COMPUTING
        if existing_status == UsageSnapshotStatus.COMPUTING and started:
            dead = UsageSnapshot.objects.for_team(self.team.id).get(id=existing.id)
            assert dead.status == UsageSnapshotStatus.ERROR

    @parameterized.expand(
        [
            ("workflow_never_started", RPCError("not found", RPCStatusCode.NOT_FOUND, b""), UsageSnapshotStatus.ERROR),
            ("workflow_started_but_reply_lost", None, UsageSnapshotStatus.COMPUTING),
        ]
    )
    def test_recompute_closes_the_row_only_when_no_workflow_started(
        self, _name: str, describe_error: RPCError | None, expected_row_status: UsageSnapshotStatus
    ) -> None:
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock(side_effect=RuntimeError("connection reset by temporal-frontend:7233"))
        temporal.get_workflow_handle.return_value.describe = AsyncMock(side_effect=describe_error)
        self.client.raise_request_exception = False

        with patch(_FLAG, return_value=True), patch(_TEMPORAL, return_value=temporal):
            response = self.client.post(f"/api/projects/{self.team.id}/data_catalog/usage/recompute/")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        row = UsageSnapshot.objects.for_team(self.team.id).get()
        assert row.status == expected_row_status
        assert row.error_message == ("" if describe_error is None else SCAN_START_FAILED_MESSAGE)

    @parameterized.expand(
        [
            ("eligible", True, False, True, True, 1),
            ("deployment_cannot_scan", False, False, True, True, 0),
            ("only_deleted_metrics", True, True, True, True, 0),
            ("no_ai_consent", True, False, False, True, 0),
            ("flag_off", True, False, True, False, 0),
            ("flag_check_fails", True, False, True, RuntimeError("flag service unavailable"), 0),
        ]
    )
    def test_weekly_run_scans_each_eligible_team_once(
        self,
        _name: str,
        supported: bool,
        metrics_deleted: bool,
        ai_approved: bool,
        flag: bool | Exception,
        expected_count: int,
    ) -> None:
        self.organization.is_ai_data_processing_approved = ai_approved
        self.organization.save()
        upsert_metric(team=self.team, user=self.user, name="mrr", description="Monthly revenue")
        upsert_metric(team=self.team, user=self.user, name="arr", description="Annual revenue")
        Metric.objects.for_team(self.team.id).update(deleted=metrics_deleted)
        flag_result = {"side_effect": flag} if isinstance(flag, Exception) else {"return_value": flag}

        with (
            patch(f"{_SCAN}.usage_scans_supported", return_value=supported),
            patch(f"{_SCAN}.posthoganalytics.feature_enabled", **flag_result),
        ):
            due = teams_due_for_scan()

        assert due.count(self.team.id) == expected_count

    def test_a_retried_create_returns_the_row_its_first_attempt_made(self) -> None:
        snapshot_id = uuid4()
        first = create_usage_snapshot(self.team.id, snapshot_id=snapshot_id)
        second = create_usage_snapshot(self.team.id, snapshot_id=snapshot_id)

        assert first.id == second.id == snapshot_id
        assert UsageSnapshot.objects.for_team(self.team.id).count() == 1
