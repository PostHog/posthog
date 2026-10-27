from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.models import Team
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.cluster_queries import (
    CLUSTER_RUN_REACH,
    ClusterRunWindow,
    load_cluster_runs,
)
from products.ai_observability.backend.logic.traces.clusters import ClusterMemberships

from .rows import T0, make_cluster, make_cluster_run_event

LISTING = "00000000-0000-0000-0000-0000000c1001"
OTHER = "00000000-0000-0000-0000-0000000c1002"


def test_the_window_starts_on_the_traces_day_and_reaches_past_the_scheduled_lookback() -> None:
    created_at = datetime(2026, 8, 12, 23, 30, tzinfo=UTC)

    window = ClusterRunWindow.for_trace(created_at)

    assert (window.start, window.end) == (datetime(2026, 8, 12, tzinfo=UTC), created_at + CLUSTER_RUN_REACH)


class TestLoadClusterRuns(ClickhouseTestMixin, BaseTest):
    @parameterized.expand(
        [
            ("a uuid", "0192b3c4-5d6e-7f80-9a1b-2c3d4e5f6a7b", [LISTING]),
            ("a slug", "support-chat-42", [LISTING]),
            ("non-ASCII", "naïve-trace", [LISTING, OTHER]),
            ("a slash", "run/42", [LISTING, OTHER]),
            ("quotes", 'id "quoted"', [LISTING, OTHER]),
            ("dots", "trace.with.dots", [LISTING, OTHER]),
            ("LIKE wildcards", "50%_off", [LISTING, OTHER]),
            ("a trailing newline", "trace-1\n", [LISTING, OTHER]),
        ]
    )
    def test_finds_runs_that_list_the_trace(self, _name: str, trace_id: str, read: list[str]) -> None:
        bulk_create_events(
            [
                make_cluster_run_event(
                    uuid=LISTING,
                    team=self.team,
                    timestamp=T0 + timedelta(days=1),
                    run_id="1_trace_20260902_030000",
                    clusters=[make_cluster(2, ["other-trace", trace_id], title="Billing questions")],
                ),
                make_cluster_run_event(
                    uuid=OTHER,
                    team=self.team,
                    timestamp=T0 + timedelta(hours=12),
                    run_id="1_trace_20260901_220000",
                    clusters=[make_cluster(0, ["other-trace"])],
                ),
            ]
        )

        rows = load_cluster_runs(self.team, None, trace_id, ClusterRunWindow.for_trace(T0))

        assert [row.uuid for row in rows] == read
        assert [(c.run_id, c.cluster_id) for c in ClusterMemberships.of(trace_id, rows).clusters] == [
            ("1_trace_20260902_030000", 2)
        ]

    def test_reads_only_runs_emitted_in_the_window(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        listing = [make_cluster(1, ["trace-1"])]
        before_the_day = "00000000-0000-0000-0000-0000000c2001"
        same_day = "00000000-0000-0000-0000-0000000c2002"
        last_day = "00000000-0000-0000-0000-0000000c2003"
        past_the_reach = "00000000-0000-0000-0000-0000000c2004"
        generation_level = "00000000-0000-0000-0000-0000000c2005"
        other_teams = "00000000-0000-0000-0000-0000000c2006"
        bulk_create_events(
            [
                make_cluster_run_event(
                    uuid=before_the_day,
                    team=self.team,
                    timestamp=datetime(2026, 8, 31, 23, tzinfo=UTC),
                    clusters=listing,
                ),
                make_cluster_run_event(
                    uuid=same_day, team=self.team, timestamp=datetime(2026, 9, 1, 2, tzinfo=UTC), clusters=listing
                ),
                make_cluster_run_event(
                    uuid=last_day, team=self.team, timestamp=datetime(2026, 9, 9, 20, tzinfo=UTC), clusters=listing
                ),
                make_cluster_run_event(
                    uuid=past_the_reach, team=self.team, timestamp=T0 + CLUSTER_RUN_REACH, clusters=listing
                ),
                make_cluster_run_event(
                    uuid=generation_level,
                    team=self.team,
                    timestamp=datetime(2026, 9, 2, 3, tzinfo=UTC),
                    clusters=listing,
                    event="$ai_generation_clusters",
                ),
                make_cluster_run_event(
                    uuid=other_teams, team=other_team, timestamp=datetime(2026, 9, 2, 3, tzinfo=UTC), clusters=listing
                ),
            ]
        )

        rows = load_cluster_runs(self.team, None, "trace-1", ClusterRunWindow.for_trace(T0))

        assert [row.uuid for row in rows] == [last_day, same_day]
