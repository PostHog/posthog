import pytest

import posthog.rate_limiting.backends as backends_module
import posthog.rate_limiting.outbound as outbound_module
import posthog.rate_limiting.policies as policies_module
from posthog.rate_limiting import OutboundRateLimiter, RatePolicy, register_policy
from posthog.rate_limiting.backends import LimitsBackend
from posthog.rate_limiting.github import acquire_github_installation, github_installation_key
from posthog.rate_limiting.policies import resolve_policy


@pytest.fixture(autouse=True)
def _reset_limiter_state():
    # Tests register throwaway domains and the GitHub-adapter test goes through the process singleton;
    # restore the registry and drop the singleton so tests stay isolated (and the import-time GitHub
    # policy survives).
    saved = dict(policies_module._REGISTRY)
    outbound_module._limiter = None
    yield
    policies_module._REGISTRY.clear()
    policies_module._REGISTRY.update(saved)
    outbound_module._limiter = None


def _fresh_limiter() -> OutboundRateLimiter:
    # Fresh backend per test so in-memory fallback state never leaks budget across tests.
    return OutboundRateLimiter(LimitsBackend())


@pytest.mark.parametrize(
    "domain,limits,n,expected",
    [
        ("test-enforce-single", ((2, 3600.0),), 1, [True, True, False]),
        ("test-enforce-weighted", ((4, 3600.0),), 2, [True, True, False]),
        # Both orderings of a two-rate policy must enforce the binding window, whichever it is —
        # guards that every rate is checked, not just items[0].
        ("test-enforce-multirate", ((2, 60.0), (100, 3600.0)), 1, [True, True, False]),
        ("test-enforce-multirate-rev", ((100, 60.0), (2, 3600.0)), 1, [True, True, False]),
    ],
)
async def test_budget_denies_once_exhausted(domain, limits, n, expected):
    # Guards seconds->window conversion and the weight passthrough: a broken item build would
    # enforce the wrong window, and a dropped weight would let n>1 burst free.
    register_policy(domain, RatePolicy(limits=limits))
    limiter = _fresh_limiter()
    key = f"{domain}:scope:1"
    assert [await limiter.acquire(key, n) for _ in expected] == expected


def test_consume_sync_enforces_budget():
    # The sync path is a distinct code path from async acquire and a real entry point — keep it
    # covered so a regression in get_client wiring or test/hit ordering is caught.
    register_policy("test-sync", RatePolicy(limits=((2, 3600.0),)))
    limiter = _fresh_limiter()
    assert [limiter.consume_sync("test-sync:scope:1") for _ in range(3)] == [True, True, False]


async def test_unique_keys_do_not_share_budget():
    # Per-key isolation: exhausting one installation's budget must not deny another, or the shared
    # GitHub budget would be enforced globally instead of per installation.
    register_policy("test-isolation", RatePolicy(limits=((1, 3600.0),)))
    limiter = _fresh_limiter()
    assert await limiter.acquire("test-isolation:scope:A", 1) is True
    assert await limiter.acquire("test-isolation:scope:A", 1) is False
    assert await limiter.acquire("test-isolation:scope:B", 1) is True


def test_policy_rejects_empty_limits():
    # A limit-less policy would let every call through; it must fail at definition time rather than
    # surfacing an opaque min() error on first acquire.
    with pytest.raises(ValueError):
        RatePolicy(limits=())


@pytest.mark.parametrize("bad_key", ["totally-unregistered:scope:1", "nocolon"])
def test_resolve_policy_rejects_bad_keys(bad_key):
    # Fail-closed: an unregistered domain or a malformed (colon-less) key must raise rather than
    # silently egress unlimited or resolve the whole string as a domain.
    with pytest.raises(ValueError):
        resolve_policy(bad_key)


async def test_falls_back_to_in_memory_when_redis_unavailable(monkeypatch):
    # Redis down must still enforce (shrunk by in_memory_divider), never allow unlimited egress.
    # Regression: an except branch that returns True instead of falling back to the local counter.
    register_policy("test-fallback", RatePolicy(limits=((4, 3600.0),), in_memory_divider=2))

    def _boom(*_args, **_kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(backends_module, "get_client", _boom)
    limiter = _fresh_limiter()
    key = "test-fallback:scope:1"
    # divider 2 -> effective in-memory limit of 2 -> third call denied
    assert [await limiter.acquire(key, 1) for _ in range(3)] == [True, True, False]


def test_weight_validation():
    # n<1 must raise, and n above the tightest limit must raise rather than spin forever (limits
    # treats a weight larger than the limit as permanently unsatisfiable).
    register_policy("test-weight", RatePolicy(limits=((3, 3600.0),)))
    limiter = _fresh_limiter()
    with pytest.raises(ValueError):
        limiter.consume_sync("test-weight:scope:1", 0)
    with pytest.raises(ValueError):
        limiter.consume_sync("test-weight:scope:1", 5)


async def test_github_adapter_registers_policy_and_keys_per_installation():
    # Importing the adapter must register the GitHub budget (else this raises) and key per
    # installation so distinct installations draw on independent budgets.
    assert github_installation_key(1) != github_installation_key(2)
    assert await acquire_github_installation(987654321, 1) is True
