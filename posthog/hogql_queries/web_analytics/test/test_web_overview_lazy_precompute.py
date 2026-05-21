from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    SessionsV2JoinMode,
    WebAnalyticsSampling,
    WebOverviewQuery,
)

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models.instance_setting import override_instance_config
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob


@override_settings(IN_UNIT_TESTING=True)
class TestWebOverviewLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

    def _enable_lazy(self):
        return override_instance_config("WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS", [self.team.pk])

    def _seed_two_sessions(self) -> None:
        # p1 has two pageviews in one session, p2 has a single pageview (bounce).
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={"$session_id": s1, "$host": "example.com", "$current_url": "https://example.com/a"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:05:00Z",
            properties={"$session_id": s1, "$host": "example.com", "$current_url": "https://example.com/b"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-03T11:00:00Z",
            properties={"$session_id": s2, "$host": "other.com", "$current_url": "https://other.com/x"},
        )

    def _build_query(
        self,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        compare: bool = False,
        conversion_goal=None,
        sampling: WebAnalyticsSampling | None = None,
        opt_in_precompute: bool = True,
    ) -> WebOverviewQuery:
        return WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            conversionGoal=conversion_goal,
            sampling=sampling,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPrecompute=True) if opt_in_precompute else None,
        )

    def _run(self, query: WebOverviewQuery):
        return WebOverviewQueryRunner(team=self.team, query=query).calculate()

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unfiltered_round_trip_creates_precompute_job(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_result(self):
        """Run the same query with and without the lazy path enabled, assert results match."""
        self._seed_two_sessions()

        # Path A: raw events scan (no lazy gate).
        raw_response = self._run(self._build_query())
        raw_visitors = raw_response.results[0].value
        raw_views = raw_response.results[1].value
        raw_sessions = raw_response.results[2].value

        # Path B: lazy precompute.
        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        # Confirm we actually went through the lazy path.
        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, "expected at least one READY precompute job"

        lazy_visitors = lazy_response.results[0].value
        lazy_views = lazy_response.results[1].value
        lazy_sessions = lazy_response.results[2].value

        assert lazy_visitors == raw_visitors, f"visitors mismatch: lazy={lazy_visitors}, raw={raw_visitors}"
        assert lazy_views == raw_views, f"views mismatch: lazy={lazy_views}, raw={raw_views}"
        assert lazy_sessions == raw_sessions, f"sessions mismatch: lazy={lazy_sessions}, raw={raw_sessions}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_host_filter_gets_distinct_cache_entry(self):
        self._seed_two_sessions()
        host_filter = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)

        with self._enable_lazy():
            self._run(self._build_query())
            unfiltered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(properties=[host_filter]))
            filtered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert unfiltered_jobs, "expected unfiltered run to create at least one job"
        assert filtered_jobs, "expected host-filtered run to create at least one job"
        assert unfiltered_jobs.isdisjoint(filtered_jobs), (
            f"unfiltered and host-filtered runs must produce distinct cache keys, "
            f"got overlap: {unfiltered_jobs & filtered_jobs}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_distinct_host_values_get_distinct_cache_entries(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
                )
            )
            example_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(
                self._build_query(
                    properties=[EventPropertyFilter(key="$host", value="other.com", operator=PropertyOperator.EXACT)]
                )
            )
            other_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert example_jobs.isdisjoint(other_jobs), (
            f"different $host values must produce distinct cache keys, got overlap: {example_jobs & other_jobs}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_disqualifying_filter_falls_through(self):
        self._seed_two_sessions()
        # $pathname is not in the MVP allowlist → gate returns False → no job created.
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        EventPropertyFilter(key="$pathname", value="/a", operator=PropertyOperator.EXACT),
                    ]
                )
            )

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_property_falls_through(self):
        # Session-level filters never qualify for MVP — only EventPropertyFilter on $host.
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        SessionPropertyFilter(key="$channel_type", value="Direct", operator=PropertyOperator.EXACT),
                    ]
                )
            )

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sampling_falls_through(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(sampling=WebAnalyticsSampling(enabled=True)))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_disabled_team_falls_through(self):
        # Both gates closed: not in allowlist AND modifier not set.
        self._seed_two_sessions()
        self._run(self._build_query(opt_in_precompute=False))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_modifier_alone_falls_through_when_team_not_enrolled(self):
        # `useWebAnalyticsPrecompute` modifier is set BUT team is not in the
        # `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` allowlist. Should fall
        # through — the env var is the operator-controlled rollout gate.
        self._seed_two_sessions()
        self._run(self._build_query(opt_in_precompute=True))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_allowlist_alone_falls_through_when_modifier_missing(self):
        # Team is in the allowlist BUT the query modifier is not set (the team
        # admin hasn't enabled the "Allow precompute" toggle in the
        # ScenePanel). Should fall through — the modifier is the per-team
        # opt-in / kill switch.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(opt_in_precompute=False))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_cache_hit_on_second_call(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())
            first_run_jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
            first_run_summary = [(str(j.id), j.status, j.error or "") for j in first_run_jobs]

            self._run(self._build_query())
            second_run_jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
            second_run_summary = [(str(j.id), j.status, j.error or "") for j in second_run_jobs]

        # The second call should not create *new* successful jobs — it should reuse ready ones.
        first_ready_ids = {jid for jid, status, _err in first_run_summary if status == PreaggregationJob.Status.READY}
        new_jobs_in_second = {jid for jid, _, _ in second_run_summary} - {jid for jid, _, _ in first_run_summary}

        assert first_ready_ids, (
            f"first run should have produced at least one READY job, statuses were: {first_run_summary}"
        )
        # Any newly-created jobs in the second call must be replacements for FAILED first-run jobs,
        # not duplicates of READY ones.
        for new_id in new_jobs_in_second:
            new_job = next(j for j in second_run_jobs if str(j.id) == new_id)
            assert new_job.status == PreaggregationJob.Status.READY
        # Most importantly: no READY job from the first run should be discarded.
        ready_jobs_preserved = first_ready_ids.issubset({jid for jid, _, _ in second_run_summary})
        assert ready_jobs_preserved, (
            f"second run dropped some first-run READY jobs. first: {first_run_summary}, second: {second_run_summary}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_to_period_reuses_cache(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())
            no_compare_jobs = {str(j.id) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

            self._run(self._build_query(compare=True))
            after_compare_jobs = {str(j.id) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        # Compare reads from the same precomputed window with a wider date range, so
        # it should reuse existing jobs and not multiply them.
        assert no_compare_jobs.issubset(after_compare_jobs)

    # --- Group A: timezone correctness --------------------------------------

    @parameterized.expand(
        [
            ("utc", "UTC"),
            ("pacific", "America/Los_Angeles"),
            ("tokyo", "Asia/Tokyo"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str) -> None:
        """Whole-hour-offset teams must produce the same metrics through the lazy and raw paths."""
        self.team.timezone = team_tz
        self.team.save()
        self._seed_two_sessions()

        raw_response = self._run(self._build_query())
        raw_values = [(r.key, r.value) for r in raw_response.results]

        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, f"expected READY precompute job for {team_tz}, got 0"

        lazy_values = [(r.key, r.value) for r in lazy_response.results]
        assert lazy_values == raw_values, f"lazy/raw mismatch for {team_tz}: raw={raw_values}, lazy={lazy_values}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_half_hour_offset_timezone_falls_through(self):
        # IST is UTC+5:30 — hourly UTC buckets can't represent the team-local
        # midnight, so the gate must refuse.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    # --- Group B: gate strictness -------------------------------------------

    @freeze_time("2024-01-15T12:00:00Z")
    def test_multiple_host_filters_fall_through(self):
        # Gate accepts at most one user-supplied property — multi-host inputs
        # collide on a single-filter cache key and must be rejected.
        self._seed_two_sessions()
        host_a = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)
        host_b = EventPropertyFilter(key="$host", value="other.com", operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query(properties=[host_a, host_b]))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_uuid_session_mode_falls_through(self):
        # `events.$session_id_uuid` would produce `uniqState(UUID)` which the
        # `(uniq, String)` column rejects non-retryably. Gate must refuse.
        self._seed_two_sessions()
        query = self._build_query()
        query.modifiers = HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID)
        with self._enable_lazy():
            self._run(query)

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("none_value", None),
            ("list_value", ["example.com", "other.com"]),
            ("empty_string", ""),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_non_string_host_value_falls_through(self, _name: str, host_value) -> None:
        self._seed_two_sessions()
        prop = EventPropertyFilter(key="$host", value=host_value, operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query(properties=[prop]))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_window_over_max_days_falls_through(self):
        # 365 days >> MAX_PRECOMPUTE_DAYS — gate refuses to avoid spawning
        # hundreds of daily INSERT jobs in one request.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(date_from="2023-01-01", date_to="2024-01-07"))

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0
