from datetime import UTC, datetime

from posthog.test.base import APIBaseTest
from unittest.mock import patch

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
