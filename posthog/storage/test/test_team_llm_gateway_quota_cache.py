from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthApplication
from posthog.models.organization import Organization
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.storage.team_llm_gateway_quota_cache import (
    AI_CREDITS_BUCKET,
    AI_GATEWAY_QUOTA_BUCKETS,
    LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET,
    LLM_GATEWAY_QUOTA_DEACTIVATED_TTL,
    LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS,
    POSTHOG_CODE_CREDITS_BUCKET,
    build_quota_blob,
    clear_team_quota,
    get_team_quota_blob,
    project_org_quota,
    project_team_quota,
    project_teams_quota_by_token,
    projected_team_ids,
    quota_blob_ttl,
    reconcile_quota_projection,
    team_llm_gateway_quota_hypercache as hypercache,
)

from ee.billing.quota_limiting import (
    QuotaLimitingCaches,
    QuotaResource,
    add_limited_team_tokens,
    get_team_limited_until,
    remove_limited_team_tokens,
)

_GATEWAY_REDIS_URL = "redis://localhost:6379/15"
_NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)


def _limit(team: Team, resource: QuotaResource, until: float) -> None:
    add_limited_team_tokens(resource, {team.api_token: int(until)}, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


def _unlimit(team: Team, resource: QuotaResource) -> None:
    remove_limited_team_tokens(resource, [team.api_token], QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY)


class QuotaProjectionTestMixin(BaseTest):
    def setUp(self):
        super().setUp()
        hypercache.cache_client.clear()
        get_client(hypercache.redis_url).delete(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET)
        for resource in (QuotaResource.AI_CREDITS, QuotaResource.POSTHOG_CODE_CREDITS):
            _unlimit(self.team, resource)

    def tearDown(self):
        for resource in (QuotaResource.AI_CREDITS, QuotaResource.POSTHOG_CODE_CREDITS):
            _unlimit(self.team, resource)
        super().tearDown()


class TestQuotaBlob(SimpleTestCase):
    def test_bucket_names_are_the_quota_resources(self):
        self.assertEqual(AI_CREDITS_BUCKET, QuotaResource.AI_CREDITS.value)
        self.assertEqual(POSTHOG_CODE_CREDITS_BUCKET, QuotaResource.POSTHOG_CODE_CREDITS.value)
        self.assertEqual(set(AI_GATEWAY_QUOTA_BUCKETS), {"ai_credits", "posthog_code_credits"})

    def test_unlimited_active_team_has_no_blob(self):
        self.assertIsNone(build_quota_blob(42, {}, True, _NOW))

    def test_limited_bucket_only_appears(self):
        until = (_NOW + timedelta(days=9)).timestamp()
        blob = build_quota_blob(42, {"posthog_code_credits": until}, True, _NOW)
        self.assertEqual(
            blob,
            {
                "team_id": 42,
                "version": 1,
                "buckets": {"posthog_code_credits": {"limited": True, "limited_until": "2026-10-01T12:00:00+00:00"}},
                "org_deactivated": False,
                "projected_at": "2026-09-22T12:00:00+00:00",
            },
        )

    def test_lapsed_score_is_not_a_limit(self):
        past = (_NOW - timedelta(seconds=1)).timestamp()
        self.assertIsNone(build_quota_blob(42, {"ai_credits": past}, True, _NOW))

    def test_deactivated_org_limits_every_bucket_without_an_end(self):
        blob = build_quota_blob(42, {}, False, _NOW)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])
        self.assertEqual(
            blob["buckets"],
            {
                "ai_credits": {"limited": True, "limited_until": None},
                "posthog_code_credits": {"limited": True, "limited_until": None},
            },
        )

    def test_ttl_runs_past_the_latest_limit_end(self):
        soon = (_NOW + timedelta(hours=1)).timestamp()
        later = (_NOW + timedelta(days=2)).timestamp()
        blob = build_quota_blob(42, {"ai_credits": soon, "posthog_code_credits": later}, True, _NOW)
        assert blob is not None
        self.assertEqual(quota_blob_ttl(blob, _NOW), 2 * 24 * 3600 + LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS)

    def test_ttl_for_a_deactivated_org_is_the_fixed_window(self):
        blob = build_quota_blob(42, {}, False, _NOW)
        assert blob is not None
        self.assertEqual(quota_blob_ttl(blob, _NOW), LLM_GATEWAY_QUOTA_DEACTIVATED_TTL)
        self.assertEqual(LLM_GATEWAY_QUOTA_DEACTIVATED_TTL, 30 * 24 * 3600)


@patch("posthog.storage.team_llm_gateway_quota_cache.settings")
class TestProjectTeamQuota(QuotaProjectionTestMixin):
    def _enable(self, mock_settings) -> None:
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL

    def test_limited_team_is_written_under_the_team_id_key(self, mock_settings):
        self._enable(mock_settings)
        until = timezone.now() + timedelta(days=3)
        _limit(self.team, QuotaResource.AI_CREDITS, until.timestamp())

        self.assertTrue(project_team_quota(self.team))

        self.assertEqual(
            hypercache.get_cache_key(self.team), f"cache/teams/{self.team.id}/team_metadata/llm_gateway_quota.json"
        )
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertEqual(blob["team_id"], self.team.id)
        self.assertEqual(blob["org_deactivated"], False)
        self.assertEqual(set(blob["buckets"]), {"ai_credits"})
        self.assertTrue(blob["buckets"]["ai_credits"]["limited"])
        self.assertIn(self.team.id, projected_team_ids())

    def test_ttl_is_the_limit_end_plus_margin(self, mock_settings):
        self._enable(mock_settings)
        until = timezone.now() + timedelta(days=3)
        _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, until.timestamp())
        with patch.object(hypercache, "set_cache_value_redis_only", wraps=hypercache.set_cache_value_redis_only) as w:
            project_team_quota(self.team)
        ttl = w.call_args.kwargs["ttl"]
        self.assertAlmostEqual(ttl, 3 * 24 * 3600 + LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS, delta=5)
        self.assertTrue(w.call_args.kwargs["track_expiry"])

    def test_both_buckets_take_the_latest_end(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(hours=1)).timestamp())
        _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, (timezone.now() + timedelta(days=5)).timestamp())
        with patch.object(hypercache, "set_cache_value_redis_only", wraps=hypercache.set_cache_value_redis_only) as w:
            project_team_quota(self.team)
        self.assertAlmostEqual(w.call_args.kwargs["ttl"], 5 * 24 * 3600 + LLM_GATEWAY_QUOTA_TTL_MARGIN_SECONDS, delta=5)
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertEqual(set(blob["buckets"]), {"ai_credits", "posthog_code_credits"})

    def test_lifting_the_limit_deletes_the_blob(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        project_team_quota(self.team)
        self.assertIsNotNone(get_team_quota_blob(self.team))

        _unlimit(self.team, QuotaResource.AI_CREDITS)
        self.assertIs(project_team_quota(self.team), False)

        # A plain delete, never a miss sentinel.
        self.assertIsNone(hypercache.cache_client.get(hypercache.get_cache_key(self.team)))
        self.assertNotIn(self.team.id, projected_team_ids())

    def test_expired_score_is_ignored(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() - timedelta(seconds=5)).timestamp())
        self.assertIs(project_team_quota(self.team), False)
        self.assertIsNone(get_team_quota_blob(self.team))

    def test_deactivated_org_projects_every_team_with_the_fixed_ttl(self, mock_settings):
        self._enable(mock_settings)
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        self.organization.is_active = False
        self.organization.save()
        with patch.object(hypercache, "set_cache_value_redis_only", wraps=hypercache.set_cache_value_redis_only) as w:
            written = project_org_quota(self.organization)
        self.assertEqual(written, 2)
        self.assertEqual({c.kwargs["ttl"] for c in w.call_args_list}, {LLM_GATEWAY_QUOTA_DEACTIVATED_TTL})
        for team in (self.team, child):
            blob = get_team_quota_blob(team)
            assert blob is not None, team.id
            self.assertTrue(blob["org_deactivated"])
            self.assertEqual(blob["buckets"]["posthog_code_credits"], {"limited": True, "limited_until": None})

    def test_child_environment_is_projected_under_its_own_id(self, mock_settings):
        self._enable(mock_settings)
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        _limit(child, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=1)).timestamp())
        try:
            self.assertEqual(project_teams_quota_by_token([child.api_token]), 1)
            blob = get_team_quota_blob(child)
            assert blob is not None
            self.assertEqual(blob["team_id"], child.id)
            self.assertIsNone(get_team_quota_blob(self.team))
        finally:
            _unlimit(child, QuotaResource.AI_CREDITS)

    def test_noop_without_gateway_redis_url(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = None
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        self.assertIsNone(project_team_quota(self.team))
        self.assertIsNone(get_team_quota_blob(self.team))
        self.assertEqual(reconcile_quota_projection(), {"candidates": 0, "written": 0, "cleared": 0, "failed": 0})

    def test_redis_failure_is_captured_not_raised(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        with (
            patch.object(hypercache, "set_cache_value_redis_only", side_effect=ConnectionError("redis down")),
            patch("posthog.storage.team_llm_gateway_quota_cache.capture_exception") as capture,
        ):
            self.assertIsNone(project_team_quota(self.team))
        capture.assert_called_once()

    def test_a_writer_that_read_stale_state_rewrites_the_current_state(self, mock_settings):
        # A writer read "limited", then the limit lifted and another writer deleted the blob before
        # this one wrote. The re-read after its write must leave the blob deleted.
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        real_write = hypercache.set_cache_value_redis_only

        def lift_then_write(*args, **kwargs):
            _unlimit(self.team, QuotaResource.AI_CREDITS)
            return real_write(*args, **kwargs)

        with patch.object(hypercache, "set_cache_value_redis_only", side_effect=lift_then_write):
            self.assertIs(project_team_quota(self.team), False)
        self.assertIsNone(get_team_quota_blob(self.team))
        self.assertNotIn(self.team.id, projected_team_ids())

    def test_a_writer_that_read_open_state_rewrites_a_new_limit(self, mock_settings):
        self._enable(mock_settings)
        real_delete = hypercache.delete_cache_entry

        def limit_then_delete(*args, **kwargs):
            _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
            return real_delete(*args, **kwargs)

        with patch.object(hypercache, "delete_cache_entry", side_effect=limit_then_delete):
            self.assertTrue(project_team_quota(self.team))
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["buckets"]["posthog_code_credits"]["limited"])

    def test_an_org_deactivated_after_the_first_read_is_rewritten(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        real_write = hypercache.set_cache_value_redis_only
        calls = iter(range(10))

        def deactivate_then_write(*args, **kwargs):
            if next(calls) == 0:
                Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
            return real_write(*args, **kwargs)

        with patch.object(hypercache, "set_cache_value_redis_only", side_effect=deactivate_then_write):
            self.assertTrue(project_team_quota(self.team))
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])

    def test_a_failed_re_read_leaves_the_writes_for_the_reconcile(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        from posthog.storage import team_llm_gateway_quota_cache as module

        real_derive = module._derive_blobs
        with (
            patch.object(
                module, "_derive_blobs", side_effect=[real_derive([self.team], timezone.now()), ConnectionError("down")]
            ),
            patch("posthog.storage.team_llm_gateway_quota_cache.capture_exception") as capture,
        ):
            self.assertTrue(project_team_quota(self.team))
        capture.assert_called_once()
        self.assertIsNotNone(get_team_quota_blob(self.team))

    def test_a_failed_rewrite_is_captured_and_not_counted(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        real_write = hypercache.set_cache_value_redis_only
        writes = iter(range(10))

        def lift_then_fail(*args, **kwargs):
            if next(writes) == 0:
                _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
                return real_write(*args, **kwargs)
            raise ConnectionError("gateway redis down")

        with (
            patch.object(hypercache, "set_cache_value_redis_only", side_effect=lift_then_fail),
            patch("posthog.storage.team_llm_gateway_quota_cache.capture_exception") as capture,
        ):
            self.assertIsNone(project_team_quota(self.team))
        capture.assert_called_once()

    def test_batches_are_bounded_and_every_team_is_projected(self, mock_settings):
        self._enable(mock_settings)
        teams = [self.team] + [Team.objects.create(organization=self.organization, name=f"b{i}") for i in range(4)]
        for team in teams:
            _limit(team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=1)).timestamp())
        from posthog.storage import team_llm_gateway_quota_cache as module

        try:
            with (
                patch.object(module, "_BATCH_SIZE", 2),
                patch.object(module, "_derive_blobs", wraps=module._derive_blobs) as derive,
            ):
                self.assertEqual(project_org_quota(self.organization), 5)
            self.assertLessEqual(max(len(call.args[0]) for call in derive.call_args_list), 2)
            for team in teams:
                self.assertIsNotNone(get_team_quota_blob(team), team.id)
        finally:
            for team in teams[1:]:
                _unlimit(team, QuotaResource.AI_CREDITS)

    def test_state_that_never_settles_gives_up_after_three_writes(self, mock_settings):
        self._enable(mock_settings)
        flips = iter(range(100))

        def flipping(teams, now):
            active = next(flips) % 2 == 1
            return {team.id: build_quota_blob(team.id, {}, active, now) for team in teams}

        with (
            patch("posthog.storage.team_llm_gateway_quota_cache._derive_blobs", side_effect=flipping),
            patch.object(hypercache, "delete_cache_entry", wraps=hypercache.delete_cache_entry) as deletes,
            patch.object(hypercache, "set_cache_value_redis_only", wraps=hypercache.set_cache_value_redis_only) as sets,
        ):
            project_team_quota(self.team)
        self.assertEqual(deletes.call_count + sets.call_count, 3)

    def test_a_writer_that_read_one_bucket_rewrites_a_second_bucket_limited_meanwhile(self, mock_settings):
        self._enable(mock_settings)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        real_write = hypercache.set_cache_value_redis_only
        calls = iter(range(10))

        def limit_code_then_write(*args, **kwargs):
            if next(calls) == 0:
                _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
            return real_write(*args, **kwargs)

        with patch.object(hypercache, "set_cache_value_redis_only", side_effect=limit_code_then_write):
            self.assertTrue(project_team_quota(self.team))
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertEqual(set(blob["buckets"]), {"ai_credits", "posthog_code_credits"})

    def test_org_flags_are_read_once_per_pass_not_per_team(self, mock_settings):
        self._enable(mock_settings)
        teams = [self.team] + [Team.objects.create(organization=self.organization, name=f"t{i}") for i in range(3)]
        for team in teams:
            _limit(team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=1)).timestamp())
        try:
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(project_org_quota(self.organization), 4)
            org_reads = [q["sql"] for q in queries.captured_queries if 'FROM "posthog_organization"' in q["sql"]]
            # One read for the write, one for the re-read, for all four teams.
            self.assertEqual(len(org_reads), 2, org_reads)
        finally:
            for team in teams[1:]:
                _unlimit(team, QuotaResource.AI_CREDITS)

    def test_a_failed_batch_read_is_captured_once_and_the_next_batch_still_projects(self, mock_settings):
        self._enable(mock_settings)
        other = Team.objects.create(organization=self.organization, name="other")
        for team in (self.team, other):
            _limit(team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=1)).timestamp())
        from posthog.storage import team_llm_gateway_quota_cache as module

        from ee.billing import quota_limiting

        real_read = quota_limiting.get_teams_limited_until

        def failing_for_first_team(tokens, resources):
            if self.team.api_token in tokens:
                raise ConnectionError("quota redis down")
            return real_read(tokens, resources)

        try:
            with (
                patch.object(module, "_BATCH_SIZE", 1),
                patch("ee.billing.quota_limiting.get_teams_limited_until", side_effect=failing_for_first_team),
                patch("posthog.storage.team_llm_gateway_quota_cache.capture_exception") as capture,
            ):
                self.assertEqual(project_teams_quota_by_token([self.team.api_token, other.api_token]), 1)
            capture.assert_called_once()
            self.assertIsNone(get_team_quota_blob(self.team))
            self.assertIsNotNone(get_team_quota_blob(other))
        finally:
            _unlimit(other, QuotaResource.AI_CREDITS)

    def test_a_failed_batch_read_is_not_retried_team_by_team(self, mock_settings):
        self._enable(mock_settings)
        teams = [self.team] + [Team.objects.create(organization=self.organization, name=f"f{i}") for i in range(3)]
        from posthog.storage import team_llm_gateway_quota_cache as module

        with (
            patch.object(module, "_derive_blobs", side_effect=ConnectionError("store down")) as derive,
            patch("posthog.storage.team_llm_gateway_quota_cache.capture_exception") as capture,
        ):
            self.assertEqual(project_org_quota(self.organization), 0)
        derive.assert_called_once()
        self.assertEqual(len(derive.call_args.args[0]), len(teams))
        capture.assert_called_once()

    def test_reachability_is_read_only_for_the_batch_teams(self, mock_settings):
        self._enable(mock_settings)
        self.organization.is_active = False
        self.organization.save()
        with CaptureQueriesContext(connection) as queries:
            project_team_quota(self.team)
        reach = [q["sql"] for q in queries.captured_queries if "posthog_projectsecretapikey" in q["sql"]]
        self.assertTrue(reach)
        for sql in reach:
            self.assertIn(f'"posthog_team"."id" IN ({self.team.id})', sql)

    def test_get_team_limited_until_reads_scores_fresh(self, mock_settings):
        until = int((timezone.now() + timedelta(days=3)).timestamp())
        _limit(self.team, QuotaResource.POSTHOG_CODE_CREDITS, until)
        limited = get_team_limited_until(self.team.api_token, AI_GATEWAY_QUOTA_BUCKETS)
        self.assertEqual(limited, {"posthog_code_credits": float(until)})
        _unlimit(self.team, QuotaResource.POSTHOG_CODE_CREDITS)
        self.assertEqual(get_team_limited_until(self.team.api_token, AI_GATEWAY_QUOTA_BUCKETS), {})


@patch("posthog.storage.team_llm_gateway_quota_cache.settings")
class TestReconcileQuotaProjection(QuotaProjectionTestMixin):
    def test_reconcile_writes_limited_removes_strays_and_is_idempotent(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        stray = Team.objects.create(organization=self.organization, name="stray")
        hypercache.set_cache_value_redis_only(stray, {"team_id": stray.id, "buckets": {}}, ttl=600, track_expiry=True)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())

        first = reconcile_quota_projection()
        self.assertEqual(first, {"candidates": 2, "written": 1, "cleared": 1, "failed": 0})
        self.assertIsNotNone(get_team_quota_blob(self.team))
        self.assertIsNone(get_team_quota_blob(stray))
        self.assertEqual(projected_team_ids(), {self.team.id})

        second = reconcile_quota_projection()
        self.assertEqual(second, {"candidates": 1, "written": 1, "cleared": 0, "failed": 0})
        self.assertEqual(projected_team_ids(), {self.team.id})

    def test_reconcile_counts_failed_writes_and_clears_apart(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        stray = Team.objects.create(organization=self.organization, name="stray")
        hypercache.set_cache_value_redis_only(stray, {"team_id": stray.id, "buckets": {}}, ttl=600, track_expiry=True)
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())

        with patch.object(hypercache, "set_cache_value_redis_only", side_effect=ConnectionError("redis down")):
            counts = reconcile_quota_projection()
        self.assertEqual(counts, {"candidates": 2, "written": 0, "cleared": 1, "failed": 1})

        hypercache.set_cache_value_redis_only(stray, {"team_id": stray.id, "buckets": {}}, ttl=600, track_expiry=True)
        with patch.object(hypercache, "delete_cache_entry", side_effect=ConnectionError("redis down")):
            counts = reconcile_quota_projection()
        self.assertEqual(counts, {"candidates": 2, "written": 1, "cleared": 0, "failed": 1})

    def test_reconcile_restamps_a_deactivated_org_that_carries_a_blob(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        self.organization.is_active = False
        self.organization.save()
        project_org_quota(self.organization)
        self.assertIn(self.team.id, projected_team_ids())

        # A fresh deactivated blob is left alone; one inside the re-stamp window is rewritten.
        self.assertEqual(reconcile_quota_projection()["candidates"], 0)
        get_client(hypercache.redis_url).zadd(
            "llm_gateway_quota_cache_expiry", {str(self.team.id): int(timezone.now().timestamp()) + 3600}
        )
        counts = reconcile_quota_projection()
        self.assertEqual(counts["written"], 1)
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])
        self.assertEqual(reconcile_quota_projection()["candidates"], 0)

    def test_reconcile_rewrites_an_evicted_deactivated_blob_whose_tracking_survived(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        self.organization.is_active = False
        self.organization.save()
        project_org_quota(self.organization)
        hypercache.cache_client.delete(hypercache.get_cache_key(self.team))
        self.assertIn(self.team.id, projected_team_ids())
        self.assertIsNone(get_team_quota_blob(self.team))

        reconcile_quota_projection()
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])

    def test_a_null_active_flag_reads_as_active(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        Organization.objects.filter(pk=self.organization.pk).update(is_active=None)
        self.organization.refresh_from_db()
        project_org_quota(self.organization)
        self.assertIsNone(get_team_quota_blob(self.team))
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        project_teams_quota_by_token([self.team.api_token])
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertFalse(blob["org_deactivated"])
        self.assertEqual(set(blob["buckets"]), {"ai_credits"})

    def test_reconcile_derives_a_deactivated_org_with_no_blob_from_postgres(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        Organization.objects.filter(pk=self.organization.pk).update(is_active=False)
        self.assertNotIn(self.team.id, projected_team_ids())

        reconcile_quota_projection()
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])

    def _deactivate_long_ago(self) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            is_active=False, updated_at=timezone.now() - timedelta(seconds=LLM_GATEWAY_QUOTA_DEACTIVATED_TTL + 60)
        )

    def test_a_long_deactivated_org_with_no_gateway_credential_loses_its_blob(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        self.organization.is_active = False
        self.organization.save()
        project_org_quota(self.organization)
        self.assertIsNotNone(get_team_quota_blob(self.team))
        self._deactivate_long_ago()

        reconcile_quota_projection()
        self.assertIsNone(get_team_quota_blob(self.team))
        self.assertNotIn(self.team.id, projected_team_ids())
        self.assertEqual(reconcile_quota_projection()["candidates"], 0)
        self.assertIsNone(get_team_quota_blob(self.team))

    @parameterized.expand(["admission_enabled", "secret_key_on_child_env", "oauth_app"])
    def test_a_long_deactivated_org_that_can_still_reach_the_gateway_keeps_its_blob(self, mock_settings, credential):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        if credential == "admission_enabled":
            Team.objects.filter(pk=self.team.pk).update(llm_gateway_enabled_at=timezone.now())
        elif credential == "secret_key_on_child_env":
            child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
            ProjectSecretAPIKey.objects.create(
                team=child, label="gateway", scopes=["llm_gateway:read"], secure_value="sha256$quota-test"
            )
        else:
            OAuthApplication.objects.create(
                name="An app",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                organization=self.organization,
                user=self.user,
            )
        self._deactivate_long_ago()

        reconcile_quota_projection()
        blob = get_team_quota_blob(self.team)
        assert blob is not None
        self.assertTrue(blob["org_deactivated"])

    def test_a_revoked_admission_does_not_keep_a_long_deactivated_blob(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        Team.objects.filter(pk=self.team.pk).update(
            llm_gateway_enabled_at=timezone.now(), llm_gateway_revoked_at=timezone.now()
        )
        ProjectSecretAPIKey.objects.create(
            team=self.team, label="not gateway", scopes=["query:read"], secure_value="sha256$quota-test-2"
        )
        self._deactivate_long_ago()
        reconcile_quota_projection()
        self.assertIsNone(get_team_quota_blob(self.team))

    def test_reconcile_untracks_a_deleted_team_once_its_blob_expired(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        client = get_client(hypercache.redis_url)
        now = int(timezone.now().timestamp())
        client.zadd(LLM_GATEWAY_QUOTA_CACHE_EXPIRY_SORTED_SET, {"987654321": now - 10, "987654322": now + 3600})
        reconcile_quota_projection()
        self.assertEqual(projected_team_ids(), {987654322})

    def test_clear_removes_blob_and_tracking(self, mock_settings):
        mock_settings.AI_GATEWAY_REDIS_URL = _GATEWAY_REDIS_URL
        _limit(self.team, QuotaResource.AI_CREDITS, (timezone.now() + timedelta(days=3)).timestamp())
        project_team_quota(self.team)
        clear_team_quota(self.team.id)
        self.assertIsNone(get_team_quota_blob(self.team))
        self.assertNotIn(self.team.id, projected_team_ids())
