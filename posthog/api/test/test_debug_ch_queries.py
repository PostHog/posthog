from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework.status import HTTP_200_OK, HTTP_403_FORBIDDEN

from posthog.api.debug_ch_queries import _cache_table_stats
from posthog.clickhouse.preaggregation.experiment_exposures_sql import SHARDED_EXPERIMENT_EXPOSURES_TABLE
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.settings.data_stores import CLICKHOUSE_AUX_CLUSTER, CLICKHOUSE_CLUSTER


class TestDebugCHQuery(APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_denied(self):
        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=True):
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

        with patch("posthog.api.debug_ch_queries.is_cloud", return_value=False):
            resp = self.client.get("/api/debug_ch_queries/")
            self.assertEqual(resp.status_code, HTTP_200_OK)

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
