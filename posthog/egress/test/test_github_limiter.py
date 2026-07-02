import uuid

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.github.limiter import _tier_budgets, observed_core_limit_cache_key
from posthog.egress.limiter.policies import Priority, resolve_policy


class TestGitHubTierBudgets(SimpleTestCase):
    # Guards the tier math: if the 90% derivation, the /18 minute scaling, or the clamps regress,
    # 5k-tier installations get budgeted above their real GitHub limit (the limiter never fires)
    # or the top tier's minute cap collapses back to the unscaled default.
    @parameterized.expand(
        [
            ("unobserved_uses_defaults", None, 13_500, 450),
            ("five_k_tier", 5_000, 4_500, 250),
            ("top_tier", 15_000, 13_500, 750),
            ("tiny_tier_hits_minute_floor", 1_000, 900, 150),
            ("huge_tier_capped_at_default", 50_000, 13_500, 750),
            ("zero_treated_as_unobserved", 0, 13_500, 450),
        ]
    )
    def test_tier_budgets(self, _name, observed, expected_hourly, expected_minute):
        assert _tier_budgets(observed) == (expected_hourly, expected_minute)

    def test_policy_reads_observed_tier_for_the_keys_installation(self):
        # Guards the wiring: key parsing + cache read + reserve attach. If resolve_policy stops
        # passing the key, or the cache key drifts from the recorder's, every installation silently
        # falls back to the flat default budget and the reserve ladder detaches.
        installation_id = f"test-{uuid.uuid4().hex[:8]}"
        cache_key = observed_core_limit_cache_key(installation_id)
        cache.set(cache_key, 5_000, 60)
        self.addCleanup(cache.delete, cache_key)

        policy = resolve_policy(f"github:installation:{installation_id}")

        assert policy.limits == ((250, 60.0), (4_500, 3600.0))
        assert policy.reserve_fraction(Priority.BATCH) > policy.reserve_fraction(Priority.NORMAL) > 0.0
        assert policy.reserve_fraction(Priority.CRITICAL) == 0.0
