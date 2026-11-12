import uuid
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.utils import timezone

from parameterized import parameterized

from posthog.models import User
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.data_modeling.backend.facade.api import mark_node_suspended, set_declared_target, sync_saved_query_to_dag
from products.data_modeling.backend.facade.models import (
    DataModelingJob,
    DataModelingJobEngine,
    DataWarehouseSavedQuery,
    Node,
)
from products.data_modeling.backend.tasks.failure_emails import (
    MAX_VIEWS_PER_DIGEST_EMAIL,
    send_matview_failure_digest,
    send_matview_failure_immediate_email,
    send_team_matview_failure_digest,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


@patch("products.data_modeling.backend.tasks.failure_emails.EmailMessage")
class TestMaterializationFailureEmails(APIBaseTest, ClickhouseTestMixin):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    def _schedule(self, saved_query: DataWarehouseSavedQuery, target: dt.timedelta) -> Node:
        node = sync_saved_query_to_dag(saved_query)
        assert node is not None
        set_declared_target(node, target)
        return node

    @parameterized.expand(
        [
            (
                "scheduled_failed_view_is_included",
                {},
                [("FAILED", dt.timedelta(hours=1), "Some error")],
                True,
            ),
            (
                "unscheduled_failing_view_is_included",
                {
                    "latest_error": "Query exceeded timeout - we limit queries to a 10-minute timeout.",
                },
                [("FAILED", dt.timedelta(hours=1), "Query exceeded timeout")],
                True,
            ),
            (
                "unscheduled_view_with_old_failure_is_skipped",
                {
                    "latest_error": "Query exceeded timeout - we limit queries to a 10-minute timeout.",
                },
                [("FAILED", dt.timedelta(days=3), "Query exceeded timeout")],
                False,
            ),
            (
                "recovered_view_is_skipped",
                {},
                [
                    ("FAILED", dt.timedelta(hours=2), "Some error"),
                    ("COMPLETED", dt.timedelta(hours=1), None),
                ],
                False,
            ),
            (
                "v2_view_with_stale_error_and_completed_run_is_skipped",
                {
                    "latest_error": "Query exceeded timeout - we limit queries to a 10-minute timeout.",
                },
                [
                    ("FAILED", dt.timedelta(days=20), "Query exceeded timeout"),
                    ("COMPLETED", dt.timedelta(hours=1), None),
                ],
                False,
            ),
            (
                "v2_failing_view_null_latest_error",
                {},
                [("FAILED", dt.timedelta(hours=1), "Some error")],
                True,
            ),
            (
                "never_deleted_view_has_null_flag",
                {"deleted": None},
                [("FAILED", dt.timedelta(hours=1), "Some error")],
                True,
            ),
            (
                # the broken parent is the one reported; mailing every descendant would bury it
                "view_blocked_by_a_broken_parent",
                {},
                [
                    ("FAILED", dt.timedelta(hours=3), "Some error"),
                    ("SKIPPED", dt.timedelta(hours=1), "Skipped because upstream view orders_daily is failing."),
                ],
                False,
            ),
        ]
    )
    def test_send_matview_failure_digest_scenarios(
        self,
        MockEmailMessage: MagicMock,
        name: str,
        saved_query_kwargs: dict,
        jobs: list[tuple[str, dt.timedelta, str | None]],
        expect_email: bool,
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"query": "SELECT 1"},
            **saved_query_kwargs,
        )
        for status, age, error in jobs:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=saved_query,
                status=getattr(DataModelingJob.Status, status),
                error=error,
                last_run_at=timezone.now() - age,
            )

        send_matview_failure_digest()

        if expect_email:
            assert len(mocked_email_messages) == 1
            assert mocked_email_messages[0].html_body
            assert name in mocked_email_messages[0].html_body
        else:
            assert len(mocked_email_messages) == 0

    def test_send_matview_failure_digest_ignores_managed_warehouse_shadow(self, MockEmailMessage: MagicMock) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="healthy_view_with_failing_shadow",
            query={"query": "SELECT 1"},
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.COMPLETED,
            last_run_at=timezone.now() - dt.timedelta(hours=2),
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.FAILED,
            engine=DataModelingJobEngine.MANAGED_WAREHOUSE,
            error="managed warehouse translation gap",
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 0

    def test_send_matview_failure_digest_shows_clickhouse_error_not_newer_shadow(
        self, MockEmailMessage: MagicMock
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="failing_view",
            query={"query": "SELECT 1"},
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.FAILED,
            error="clickhouse boom",
            last_run_at=timezone.now() - dt.timedelta(hours=2),
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.FAILED,
            engine=DataModelingJobEngine.MANAGED_WAREHOUSE,
            error="managed warehouse boom",
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 1
        assert "clickhouse boom" in mocked_email_messages[0].html_body
        assert "managed warehouse boom" not in mocked_email_messages[0].html_body

    def test_send_matview_failure_digest_not_sent_by_default(self, MockEmailMessage: MagicMock) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        # View that would trigger an email (scheduled + recent failed job), but user hasn't opted in.
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="test_materialized_view",
            query={"query": "SELECT 1"},
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=saved_query,
            status=DataModelingJob.Status.FAILED,
            error="Some error",
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )
        send_matview_failure_digest()

        assert len(mocked_email_messages) == 0

    def test_send_matview_failure_digest_kitchen_sink_snapshot(self, MockEmailMessage: MagicMock) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        failed_cases = [
            (
                "events_by_day_rollup",
                "Code: 241. DB::Exception: Memory limit (for query) exceeded: "
                "would use 15.00 GiB (attempt to allocate chunk of 4194304 bytes)",
            ),
            (
                "weekly_retention_matrix",
                "Code: 43. DB::Exception: Illegal type Nullable(Float64) of argument for aggregate function sum",
            ),
            (
                "signups_by_utm_source",
                "HogQL: unknown property `utm_soruce` on table `events` — did you mean `utm_source`?",
            ),
        ]
        for name, error in failed_cases:
            sq = DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"query": "SELECT 1"},
                is_materialized=True,
            )
            self._schedule(sq, dt.timedelta(hours=1))
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=sq,
                status=DataModelingJob.Status.FAILED,
                error=error,
                last_run_at=timezone.now() - dt.timedelta(hours=1),
            )

        unscheduled_cases = [
            ("heavy_joins_with_warehouse", "Query timed out after 900 seconds"),
            ("experimental_feature_funnels", "Query timed out after 900 seconds"),
        ]
        for name, error in unscheduled_cases:
            sq = DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"query": "SELECT 1"},
                latest_error=error,
                is_materialized=False,
            )
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=sq,
                status=DataModelingJob.Status.FAILED,
                error=error,
                last_run_at=timezone.now() - dt.timedelta(hours=1),
            )

        # Pausing keeps `is_materialized` and the table but clears the node target, so it can't retry.
        # The legacy column can still hold a cadence, and the digest must not read it as scheduled.
        paused = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="paused_orders_rollup",
            query={"query": "SELECT 1"},
            sync_frequency_interval=dt.timedelta(hours=1),
            is_materialized=True,
            table=DataWarehouseTable.objects.create(team=self.team, name="paused_orders_rollup", format="Delta"),
        )
        tiered = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="tiered_daily_active_users",
            query={"query": "SELECT 1"},
            is_materialized=True,
        )
        tiered_node = self._schedule(tiered, dt.timedelta(hours=1))
        for sq in (paused, tiered):
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=sq,
                status=DataModelingJob.Status.FAILED,
                error="Code: 241. DB::Exception: Memory limit (for query) exceeded",
                last_run_at=timezone.now() - dt.timedelta(hours=1),
            )

        # A success breaks the streak, so only the three failures after it count.
        ongoing = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="nightly_revenue_rollup",
            query={"query": "SELECT 1"},
            is_materialized=True,
        )
        self._schedule(ongoing, dt.timedelta(days=1))
        streak_started_at = timezone.now() - dt.timedelta(days=3)
        for status, run_at in [
            ("FAILED", timezone.now() - dt.timedelta(days=9)),
            ("COMPLETED", timezone.now() - dt.timedelta(days=6)),
            ("FAILED", streak_started_at),
            ("FAILED", timezone.now() - dt.timedelta(days=2)),
            ("FAILED", timezone.now() - dt.timedelta(hours=1)),
        ]:
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=ongoing,
                status=getattr(DataModelingJob.Status, status),
                error="Code: 60. DB::Exception: Unknown table expression identifier",
                last_run_at=run_at,
            )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 1
        message = mocked_email_messages[0]
        assert message.subject == (
            f"PostHog: 3 materialized views need action, 4 started failing, 1 is still failing in {self.team.name}"
        )
        sections = {s["key"]: [v["name"] for v in s["views"]] for s in message.properties["sections"]}
        assert list(sections) == ["action", "new", "ongoing"]
        assert sorted(sections["action"]) == sorted([*(name for name, _ in unscheduled_cases), paused.name])
        assert sorted(sections["new"]) == sorted([*(name for name, _ in failed_cases), tiered.name])
        assert sections["ongoing"] == ["nightly_revenue_rollup"]
        ongoing_row = next(v for v in message.properties["views"] if v["name"] == "nightly_revenue_rollup")
        assert ongoing_row["failed_runs"] == 3
        assert ongoing_row["failing_since"] == streak_started_at.strftime("%b %d, %H:%M UTC")
        # A view with a DAG node opens its node detail; one without falls back to the SQL editor.
        urls = {v["name"]: v["url"] for v in message.properties["views"]}
        assert urls[tiered.name].endswith(f"/project/{self.team.id}/models/{tiered_node.id}")
        assert urls[paused.name].endswith(f"/project/{self.team.id}/sql?open_view={paused.id}")

        html = message.html_body
        assert html.count("Not scheduled.") == len(unscheduled_cases)
        assert html.count("Paused.") == 1
        assert html.count("First failed") == len(failed_cases) + 1
        assert "3 failed runs" in html
        assert "select Resume" not in html

    @parameterized.expand(
        [
            ("over_limit", "A" * 500, "A" * 252 + "..."),
            ("at_limit", "A" * 255, "A" * 255),
            ("under_limit", "A" * 100, "A" * 100),
        ]
    )
    def test_send_matview_failure_digest_truncates_long_errors(
        self, MockEmailMessage: MagicMock, name: str, error: str, expected_error: str
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="long_error_view",
            query={"query": "SELECT 1"},
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=sq,
            status=DataModelingJob.Status.FAILED,
            error=error,
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 1
        rendered_error = mocked_email_messages[0].properties["views"][0]["error"]
        assert rendered_error == expected_error
        assert len(rendered_error) <= 255

    @parameterized.expand(
        [
            (
                "job_error_is_shown",
                "Code: 241. DB::Exception: Memory limit (for query) exceeded",
                None,
                "Code: 241. DB::Exception: Memory limit (for query) exceeded",
                False,
            ),
            ("long_job_error_is_truncated", "B" * 500, None, "B" * 252 + "...", False),
            (
                "falls_back_to_the_saved_query_error",
                "",
                "Query exceeded timeout limit",
                "Query exceeded timeout limit",
                False,
            ),
            ("suspension_says_so_and_how_to_resume", "boom", None, "boom", True),
        ]
    )
    def test_send_matview_failure_immediate_email_includes_the_error(
        self,
        MockEmailMessage: MagicMock,
        _name: str,
        job_error: str,
        latest_error: str | None,
        expected_error: str,
        suspended: bool,
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {
            "materialized_view_sync_failed": True,
            "materialized_view_sync_failed_immediate": True,
        }
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="failing_view",
            query={"query": "SELECT 1"},
            latest_error=latest_error,
        )
        job = DataModelingJob.objects.create(
            team=self.team,
            saved_query=sq,
            status=DataModelingJob.Status.FAILED,
            error=job_error,
            last_run_at=timezone.now(),
        )

        send_matview_failure_immediate_email(self.team.id, str(sq.id), str(job.id), suspended=suspended)

        assert len(mocked_email_messages) == 1
        message = mocked_email_messages[0]
        assert message.properties["error"] == expected_error
        assert expected_error[:80] in message.html_body
        # A distinct key, or the suspension email dedupes against a failure email for the same job.
        assert message.campaign_key.startswith("matview_suspended_" if suspended else "matview_failure_immediate_")
        assert ("was suspended" in message.subject) == suspended
        assert ("select Resume" in message.html_body) == suspended

    def test_send_matview_failure_digest_splits_by_view_access(self, MockEmailMessage: MagicMock) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        for user in (self.user, self._create_user("restricted@posthog.com")):
            user.partial_notification_settings = {"materialized_view_sync_failed": True}
            user.save()

        for name in ("shared_view", "restricted_view"):
            sq = DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                query={"query": "SELECT 1", "kind": "HogQLQuery"},
            )
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=sq,
                status=DataModelingJob.Status.FAILED,
                error=f"{name} broke",
                last_run_at=timezone.now(),
            )

        class FakeUserAccessControl:
            def __init__(self, user: User, team: object) -> None:
                self.user = user

            access_controls_supported = True
            is_organization_admin = False

            def check_access_level_for_resource(self, resource: str, level: str) -> bool:
                return True

            def check_access_level_for_object(self, obj: DataWarehouseSavedQuery, required_level: str) -> bool:
                return not (self.user.email == "restricted@posthog.com" and obj.name == "restricted_view")

        with patch("products.data_modeling.backend.tasks.failure_emails.UserAccessControl", FakeUserAccessControl):
            send_matview_failure_digest()

        assert len(mocked_email_messages) == 2
        named = sorted(tuple(sorted(v["name"] for v in m.properties["views"])) for m in mocked_email_messages)
        assert named == [("restricted_view", "shared_view"), ("shared_view",)]

        restricted_email = next(m for m in mocked_email_messages if len(m.properties["views"]) == 1)
        assert "restricted_view" not in restricted_email.html_body
        assert "restricted_view broke" not in restricted_email.html_body

    def test_send_matview_failure_digest_retries_when_no_audience_can_be_resolved(
        self, MockEmailMessage: MagicMock
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="broken_view",
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            is_materialized=True,
        )

        class UnreachableUserAccessControl:
            def __init__(self, user: User, team: object) -> None:
                pass

            access_controls_supported = True
            is_organization_admin = False

            def check_access_level_for_resource(self, resource: str, level: str) -> bool:
                return True

            def check_access_level_for_object(self, obj: DataWarehouseSavedQuery, required_level: str) -> bool:
                raise OperationalError("access control store is down")

        with patch(
            "products.data_modeling.backend.tasks.failure_emails.UserAccessControl", UnreachableUserAccessControl
        ):
            with self.assertRaises(OperationalError):
                send_team_matview_failure_digest(self.team.id, [str(sq.id)], [])

        assert len(mocked_email_messages) == 0

    @parameterized.expand(
        [
            (
                "serving_marker",
                DataModelingJobEngine.CLICKHOUSE,
                False,
                [("suspended_view", True), ("retrying_view", False)],
                True,
            ),
            ("shadow_marker_only", DataModelingJobEngine.LEGACY_DUCKGRES, False, [("retrying_view", False)], False),
            ("reverted_after_suspension", DataModelingJobEngine.CLICKHOUSE, True, [("retrying_view", False)], False),
        ]
    )
    def test_send_matview_failure_digest_marks_a_row_suspended_only_on_a_live_serving_marker(
        self,
        MockEmailMessage: MagicMock,
        _name: str,
        marker_engine: str,
        revert: bool,
        expected_rows: list[tuple[str, bool]],
        expected_has_suspended: bool,
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        suspended = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="suspended_view",
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            is_materialized=True,
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=suspended,
            status=DataModelingJob.Status.FAILED,
            # Suspending rewrites the job error to lead with this sentence, so the row must not use it.
            error=(
                "This model has been suspended after 5 consecutive failed materializations. "
                "Error: Code: 241. DB::Exception: Memory limit (for query) exceeded"
            ),
            last_run_at=timezone.now() - dt.timedelta(days=4),
        )
        node = self._schedule(suspended, dt.timedelta(hours=1))
        mark_node_suspended(
            node,
            engine=marker_engine,
            reason="Code: 241. DB::Exception: Memory limit (for query) exceeded",
            job_id=str(uuid.uuid4()),
        )
        node.save()

        if revert:
            suspended.revert_materialization()

        retrying = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="retrying_view",
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            is_materialized=True,
        )
        self._schedule(retrying, dt.timedelta(hours=1))
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=retrying,
            status=DataModelingJob.Status.FAILED,
            error="Query exceeded timeout limit",
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 1
        views = mocked_email_messages[0].properties["views"]
        assert [(v["name"], v["suspended"]) for v in views] == expected_rows

        html = mocked_email_messages[0].html_body
        assert "Started failing" in html
        if expected_has_suspended:
            assert "select Resume" in html
            assert "Memory limit (for query) exceeded" in html
            assert "has been suspended after" not in html
        else:
            assert "select Resume" not in html
            assert "suspended_view" not in html

    def test_send_matview_failure_digest_caps_the_rows_and_counts_the_rest(self, MockEmailMessage: MagicMock) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {"materialized_view_sync_failed": True}
        self.user.save()

        for index in range(MAX_VIEWS_PER_DIGEST_EMAIL + 4):
            sq = DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"failing_view_{index}",
                query={"query": "SELECT 1"},
            )
            DataModelingJob.objects.create(
                team=self.team,
                saved_query=sq,
                status=DataModelingJob.Status.FAILED,
                error="Query exceeded timeout limit",
                last_run_at=timezone.now() - dt.timedelta(minutes=index + 1),
            )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == 1
        assert len(mocked_email_messages[0].properties["views"]) == MAX_VIEWS_PER_DIGEST_EMAIL
        assert mocked_email_messages[0].properties["omitted_count"] == 4
        assert "4</strong> more failing views" in mocked_email_messages[0].html_body

    @parameterized.expand(
        [
            (
                "immediate_on",
                {"materialized_view_sync_failed": True, "materialized_view_sync_failed_immediate": True},
                True,
            ),
            (
                "immediate_off",
                {"materialized_view_sync_failed": True, "materialized_view_sync_failed_immediate": False},
                False,
            ),
            ("immediate_unset_defaults_off", {"materialized_view_sync_failed": True}, False),
            (
                "both_deliveries_on",
                {
                    "materialized_view_sync_failed": True,
                    "materialized_view_sync_failed_daily": True,
                    "materialized_view_sync_failed_immediate": True,
                },
                True,
            ),
            (
                "master_off_wins",
                {"materialized_view_sync_failed": False, "materialized_view_sync_failed_immediate": True},
                False,
            ),
        ]
    )
    def test_send_matview_failure_immediate_email_respects_immediate_preference(
        self, MockEmailMessage: MagicMock, name: str, notification_settings: dict, expect_email: bool
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = notification_settings
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(team=self.team, name="failing_view", query={"query": "SELECT 1"})
        job = DataModelingJob.objects.create(
            team=self.team,
            saved_query=sq,
            status=DataModelingJob.Status.FAILED,
            error="Some error",
            last_run_at=timezone.now(),
        )

        send_matview_failure_immediate_email(self.team.id, str(sq.id), str(job.id))

        if expect_email:
            assert len(mocked_email_messages) == 1
            assert mocked_email_messages[0].send.call_count == 1
            assert "failing_view" in mocked_email_messages[0].html_body
        else:
            assert len(mocked_email_messages) == 0

    @parameterized.expand(
        [
            ("warehouse_access_granted", True, True, True, True),
            ("warehouse_access_denied", True, False, True, False),
            ("this_view_denied", True, True, False, False),
            ("access_controls_unavailable_still_sends", False, False, False, True),
        ]
    )
    def test_send_matview_failure_immediate_email_respects_warehouse_access(
        self,
        MockEmailMessage: MagicMock,
        name: str,
        access_controls_supported: bool,
        has_warehouse_access: bool,
        has_view_access: bool,
        expect_email: bool,
    ) -> None:
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = {
            "materialized_view_sync_failed": True,
            "materialized_view_sync_failed_immediate": True,
        }
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(team=self.team, name="failing_view", query={"query": "SELECT 1"})
        job = DataModelingJob.objects.create(
            team=self.team,
            saved_query=sq,
            status=DataModelingJob.Status.FAILED,
            error="Some error",
            last_run_at=timezone.now(),
        )

        class FakeUserAccessControl:
            def __init__(self, user: object, team: object) -> None:
                pass

            @property
            def access_controls_supported(self) -> bool:
                return access_controls_supported

            @property
            def is_organization_admin(self) -> bool:
                return False

            def check_access_level_for_resource(self, resource: str, level: str) -> bool:
                return has_warehouse_access

            def check_access_level_for_object(self, obj: object, required_level: str) -> bool:
                return has_view_access

        with patch("products.data_modeling.backend.tasks.failure_emails.UserAccessControl", FakeUserAccessControl):
            send_matview_failure_immediate_email(self.team.id, str(sq.id), str(job.id))

        assert len(mocked_email_messages) == (1 if expect_email else 0)

    @parameterized.expand(
        [
            ("daily_on", {"materialized_view_sync_failed": True, "materialized_view_sync_failed_daily": True}, True),
            ("daily_off", {"materialized_view_sync_failed": True, "materialized_view_sync_failed_daily": False}, False),
            ("daily_unset_defaults_on", {"materialized_view_sync_failed": True}, True),
            (
                "both_deliveries_on",
                {
                    "materialized_view_sync_failed": True,
                    "materialized_view_sync_failed_daily": True,
                    "materialized_view_sync_failed_immediate": True,
                },
                True,
            ),
            (
                "immediate_only_still_skips_digest",
                {
                    "materialized_view_sync_failed": True,
                    "materialized_view_sync_failed_daily": False,
                    "materialized_view_sync_failed_immediate": True,
                },
                False,
            ),
            (
                "master_off_wins",
                {"materialized_view_sync_failed": False, "materialized_view_sync_failed_daily": True},
                False,
            ),
        ]
    )
    def test_send_matview_failure_digest_respects_daily_preference(
        self, MockEmailMessage: MagicMock, name: str, notification_settings: dict, expect_email: bool
    ) -> None:

        mocked_email_messages = mock_email_messages(MockEmailMessage)

        self.user.partial_notification_settings = notification_settings
        self.user.save()

        sq = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="failing_view",
            query={"query": "SELECT 1"},
        )
        DataModelingJob.objects.create(
            team=self.team,
            saved_query=sq,
            status=DataModelingJob.Status.FAILED,
            error="Some error",
            last_run_at=timezone.now() - dt.timedelta(hours=1),
        )

        send_matview_failure_digest()

        assert len(mocked_email_messages) == (1 if expect_email else 0)
