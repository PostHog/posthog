from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN

from posthog.api.debug_ch_queries import _cache_table_stats
from posthog.clickhouse.preaggregation.experiment_exposures_sql import SHARDED_EXPERIMENT_EXPOSURES_TABLE
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.settings.data_stores import CLICKHOUSE_AUX_CLUSTER, CLICKHOUSE_CLUSTER

from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


class TestDebugCHQuery(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_denied(self):
        with patch("posthog.api.debug_ch_queries.DEBUG", True):
            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

        with patch("posthog.api.debug_ch_queries.DEBUG", False):
            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

            self.user.is_staff = True
            self.user.save()

            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

    def test_non_staff_denied_off_cloud(self):
        # Self-hosted is not single-tenant: a plain member of one team must not read the executed
        # query text of every other team on the instance.
        self.assertFalse(self.user.is_staff)

        with self.is_cloud(False), patch("posthog.api.debug_ch_queries.DEBUG", False):
            resp = self.client.get("/api/debug_ch_queries/?insight_id=1")

        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN, resp.content)

    @patch("posthog.api.debug_ch_queries.sync_execute")
    def test_filtered_queries_are_scoped_to_the_requesting_users_team(self, mock_sync_execute):
        # insight ids are sequential and the log_comment filter alone matches any team's rows,
        # so every filtered read must also bind the requester's team.
        def fake_sync_execute(sql, params):
            return [(0, 0, 0.0, 0.0, 0.0)] if "total_queries" in sql else []

        mock_sync_execute.side_effect = fake_sync_execute
        self.user.is_staff = True
        self.user.save()

        resp = self.client.get("/api/debug_ch_queries/?insight_id=1")

        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
        self.assertTrue(mock_sync_execute.call_args_list)
        for sql, params in (call.args for call in mock_sync_execute.call_args_list):
            self.assertIn("%(team_id)s", sql)
            self.assertEqual(params["team_id"], self.team.pk)

    def test_filtered_queries_denied_when_requester_has_no_current_team(self):
        # A filtered read scopes to the requester's team; without one, refuse rather
        # than fall through to an unscoped read across every team on the instance.
        new_user = User.objects.create_user(
            email="staff-no-team@posthog.com", password="testpass123", first_name="Staff", is_staff=True
        )
        self.client.force_login(new_user)

        resp = self.client.get("/api/debug_ch_queries/?insight_id=1")

        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN, resp.content)

    def _create_pat(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def test_slowest_queries_pat_requires_scope_and_staff(self):
        # Without the query_performance scope, even a staff user is rejected.
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["experiment:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    def test_slowest_queries_wildcard_pat_rejected(self):
        # A full-access (`*`) PAT must NOT satisfy the query_performance:read requirement —
        # the view's `scope_object = "INTERNAL"` blocks the wildcard short-circuit, so a PAT
        # must carry `query_performance:read` explicitly.
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["*"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN, resp.content)

    def test_slowest_queries_pat_with_scope_but_non_staff_rejected(self):
        # Scope grants the PAT past the scope check; is_staff still gates the action.
        self.assertFalse(self.user.is_staff)
        token = self._create_pat(scopes=["query_performance:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

    def test_cache_growth_series_are_preseeded_and_bucket_aligned(self):
        # The charts index series arrays by bucket position, so a table with no builds in the
        # window must still return zero-filled arrays, and returned rows must land in the bucket
        # matching their ISO key — not be appended positionally.
        self.user.is_staff = True
        self.user.save()
        bucket = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")

        with patch(
            "posthog.api.debug_ch_queries.sync_execute",
            return_value=[(bucket, "exposures", 10, 100)],
        ):
            resp = self.client.get("/api/debug_ch_queries/cache_growth/?hours=336")

        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
        data = resp.json()
        i = data["buckets"].index(bucket)
        for table in ("exposures", "metric_events"):
            self.assertEqual(len(data["tables"][table]["written_rows"]), len(data["buckets"]))
        self.assertEqual(data["tables"]["exposures"]["written_rows"][i], 10)
        self.assertEqual(data["tables"]["exposures"]["written_bytes"][i], 100)
        self.assertEqual(sum(data["tables"]["metric_events"]["written_rows"]), 0)

    @patch("posthog.api.debug_ch_queries.sync_execute", return_value=[])
    def test_slowest_queries_pat_with_scope_and_staff_allowed(self, _mock_execute):
        self.user.is_staff = True
        self.user.save()
        token = self._create_pat(scopes=["query_performance:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/slowest_queries/?hours=1",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)


class TestPrecomputeHealth(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        cache.clear()  # the endpoint caches complete payloads; tests must not share them

    def _create_pat(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def test_scope_and_staff_gate_wired_on_action(self) -> None:
        # The scope/wildcard/staff mechanics are proven on slowest_queries; this
        # only guards that THIS action declares the scope and the staff check.
        token = self._create_pat(scopes=["query_performance:read"])
        self.client.logout()

        resp = self.client.get(
            "/api/debug_ch_queries/precompute_health/",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(resp.status_code, HTTP_403_FORBIDDEN)

        self.user.is_staff = True
        self.user.save()
        with patch("posthog.api.debug_ch_queries.sync_execute", return_value=[]):
            resp = self.client.get(
                "/api/debug_ch_queries/precompute_health/",
                headers={"authorization": f"Bearer {token}"},
            )
            self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)

            # An unregistered product must be rejected before any scan runs.
            resp = self.client.get(
                "/api/debug_ch_queries/precompute_health/?product=nonsense",
                headers={"authorization": f"Bearer {token}"},
            )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_assembles_ratio_from_query_log_rows(self) -> None:
        self.user.is_staff = True
        self.user.save()

        hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        results = iter(
            [
                [(hour.replace(tzinfo=None), 750, 250, 12)],  # hourly: lazy, eligible_live, live_errored
                [(hour.replace(tzinfo=None), 12000, 2100, 3)],  # warming: queries, teams, errored
                [("web_overview_query", 180, 9), ("stats_table_main_query", 70, 0)],
                [(2, 120, 5), (1589, 60, 0)],  # top_missing_teams
                [(2, 45210, 3811.5, 4)],  # top_warmed_teams
            ]
        )
        call_count = {"n": 0}

        def fake_sync_execute(*_a, **_k):
            call_count["n"] += 1
            return next(results)

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=fake_sync_execute):
            resp = self.client.get("/api/debug_ch_queries/precompute_health/?hours=9999")

        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
        data = resp.json()
        self.assertEqual(data["hours"], 168)  # clamped
        self.assertEqual(data["unavailable_sections"], [])
        self.assertEqual(
            data["summary"], {"lazy_hits": 750, "eligible_live": 250, "live_errored": 12, "hit_ratio": 75.0}
        )
        # Series are zero-filled over the whole window with explicit UTC stamps —
        # a silent hour must read as zero, and the data hour must land in place.
        self.assertEqual(len(data["hourly"]), 169)
        (data_hour,) = [e for e in data["hourly"] if e["lazy_hits"]]
        self.assertEqual(data_hour["hour"], hour.isoformat())
        self.assertEqual(data_hour["hit_ratio"], 75.0)
        self.assertEqual(sum(e["queries"] for e in data["warming"]), 12000)
        self.assertEqual(data["miss_breakdown"][0], {"query_type": "web_overview_query", "misses": 180, "errored": 9})
        self.assertEqual(data["top_missing_teams"][0], {"team_id": 2, "misses": 120, "errored": 5})
        self.assertEqual(
            data["top_warmed_teams"][0],
            {"team_id": 2, "warming_queries": 45210, "warming_seconds": 3811.5, "errored": 4},
        )
        self.assertEqual(data["product"], "web_analytics")

        # A complete payload is cached: an identical request runs no new scans.
        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=AssertionError("must be cached")):
            resp2 = self.client.get("/api/debug_ch_queries/precompute_health/?hours=9999")
        self.assertEqual(resp2.status_code, HTTP_200_OK, resp2.content)
        self.assertEqual(resp2.json()["summary"], data["summary"])

    def test_failed_section_degrades_to_partial_response(self) -> None:
        # One slow scan (timeout, OOM) must cost its own section, not 500 the
        # whole response — and a partial payload must not be cached as complete.
        self.user.is_staff = True
        self.user.save()

        def fake_sync_execute(query: str, *_a, **_k) -> list:
            if "'trigger'" in query or '"trigger"' in query:
                raise Exception("Code: 159. DB::Exception: Timeout exceeded")
            return []

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=fake_sync_execute):
            resp = self.client.get("/api/debug_ch_queries/precompute_health/")

        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
        data = resp.json()
        self.assertEqual(data["unavailable_sections"], ["warming", "top_warmed_teams"])
        self.assertEqual(data["warming"], [])
        self.assertEqual(len(data["hourly"]), 25)  # healthy sections still zero-fill

        # Not cached: the next request must re-run the scans.
        calls = {"n": 0}

        def counting_sync_execute(*_a, **_k) -> list:
            calls["n"] += 1
            return []

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=counting_sync_execute):
            self.client.get("/api/debug_ch_queries/precompute_health/")
        self.assertGreater(calls["n"], 0)

    def test_team_filter_narrows_all_sections_and_skips_team_ranking(self) -> None:
        # A per-team read must inject the tenant filter into every section's SQL,
        # swap the fleet-wide team ranking for the per-strategy triage detail, and
        # never run an unfiltered scan.
        self.user.is_staff = True
        self.user.save()

        executed: list[tuple[str, dict]] = []

        def fake_sync_execute(query: str, params: dict, **_kwargs) -> list:
            executed.append((query, params))
            return []

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=fake_sync_execute):
            resp = self.client.get("/api/debug_ch_queries/precompute_health/?team_id=42")

        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)
        self.assertEqual(len(executed), 4)  # hourly, warming, miss_breakdown, query_detail
        for query, params in executed:
            self.assertIn("JSONExtractInt(log_comment, 'team_id') = %(team_id)s", query)
            self.assertEqual(params["team_id"], 42)
        self.assertEqual(resp.json()["team_id"], 42)
        self.assertEqual(resp.json()["top_missing_teams"], [])
        self.assertEqual(resp.json()["top_warmed_teams"], [])
        self.assertEqual(resp.json()["query_detail"], [])
        self.assertEqual(resp.json()["unavailable_sections"], [])


class TestCacheTableStats(SimpleTestCase):
    def test_reads_each_table_from_its_own_cluster(self):
        # The metric-events sharded table lives on the aux cluster; reading system.parts only on
        # the main cluster silently reported it as empty in prod. This fails if the per-cluster
        # dispatch is reverted to a single main-cluster query.
        def fake_sync_execute(_query, params):
            parts_by_cluster = {
                CLICKHOUSE_CLUSTER: [(SHARDED_EXPERIMENT_EXPOSURES_TABLE(), "20260801", 10, 100, 1)],
                CLICKHOUSE_AUX_CLUSTER: [(SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE(), "20260802", 20, 200, 2)],
            }
            return [row for row in parts_by_cluster[params["cluster"]] if row[0] in params["tables"]]

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=fake_sync_execute):
            stats = {entry["table"]: entry for entry in _cache_table_stats()}

        exposures = stats["experiment_exposures_preaggregated"]
        metric_events = stats["experiment_metric_events_preaggregated"]
        self.assertEqual(exposures["total_rows"], 10)
        self.assertEqual(exposures["newest_partition"], "20260801")
        self.assertEqual(metric_events["total_rows"], 20)
        self.assertEqual(metric_events["active_parts"], 2)
        self.assertEqual(
            metric_events["partitions"], [{"partition": "20260802", "rows": 20, "bytes_on_disk": 200, "parts": 2}]
        )

    def test_unreachable_cluster_degrades_instead_of_raising(self):
        # A deployment without the aux cluster (or an aux outage) must not 500 the whole
        # endpoint and lose the stats already readable from the main cluster.
        def fake_sync_execute(_query, params):
            if params["cluster"] == CLICKHOUSE_AUX_CLUSTER:
                raise Exception("Requested cluster 'aux' not found")
            return [(SHARDED_EXPERIMENT_EXPOSURES_TABLE(), "20260801", 10, 100, 1)]

        with patch("posthog.api.debug_ch_queries.sync_execute", side_effect=fake_sync_execute):
            stats = {entry["table"]: entry for entry in _cache_table_stats()}

        exposures = stats["experiment_exposures_preaggregated"]
        metric_events = stats["experiment_metric_events_preaggregated"]
        self.assertEqual(exposures["total_rows"], 10)
        self.assertNotIn("unavailable", exposures)
        self.assertTrue(metric_events["unavailable"])
        self.assertEqual(metric_events["total_rows"], 0)


class TestPrecomputationTeamsUpdate(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_staff_toggle_stamps_manual_provenance(self):
        # A missing stamp would let the auto-enrollment job override a human's disable
        # on its next run.
        self.user.is_staff = True
        self.user.save()

        resp = self.client.post(
            "/api/debug_ch_queries/precomputation_teams/",
            {"team_id": self.team.id, "experiment_precomputation_enabled": False},
        )
        self.assertEqual(resp.status_code, HTTP_200_OK, resp.content)

        config = TeamExperimentsConfig.objects.get(team=self.team)
        self.assertFalse(config.experiment_precomputation_enabled)
        self.assertEqual(config.precomputation_enabled_set_by, TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL)
