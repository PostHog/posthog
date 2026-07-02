import pytest

import posthog.egress.limiter.backends as backends_module
import posthog.egress.limiter.outbound as outbound_module
import posthog.egress.limiter.policies as policies_module
from posthog.egress.github.limiter import acquire_github_installation, github_installation_key
from posthog.egress.limiter.backends import LimitsBackend
from posthog.egress.limiter.outbound import OutboundRateLimiter
from posthog.egress.limiter.policies import Priority, RatePolicy, register_policy, resolve_policy


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


_RESERVE = {Priority.NORMAL: 0.1, Priority.BATCH: 0.3}


@pytest.mark.parametrize(
    "priority,grantable",
    [
        # reserve floor = floor(fraction * 10): CRITICAL 0, NORMAL 1, BATCH 3 -> each priority may
        # consume up to limit - floor before its reserved headroom denies the next call.
        (Priority.CRITICAL, 10),
        (Priority.NORMAL, 9),
        (Priority.BATCH, 7),
    ],
)
async def test_reserved_floor_caps_each_priority(priority, grantable):
    # The whole point of the lane: a lower priority is denied while headroom is still owed to higher
    # ones, even though all three draw from the same counter.
    register_policy("test-reserve", RatePolicy(limits=((10, 3600.0),), reserve=_RESERVE))
    limiter = _fresh_limiter()
    # Distinct scope per case — parametrize cases share one Redis-backed counter otherwise.
    key = f"test-reserve:scope:{priority.value}"
    grants = [await limiter.acquire(key, priority=priority) for _ in range(11)]
    assert grants[:grantable] == [True] * grantable
    assert grants[grantable] is False


async def test_batch_shed_before_critical_on_shared_counter():
    # Fill the non-reserved share with BATCH, then prove BATCH is denied while CRITICAL still draws
    # from the SAME counter (the reserved floor protected exactly that headroom).
    register_policy("test-shared", RatePolicy(limits=((10, 3600.0),), reserve={Priority.BATCH: 0.3}))
    limiter = _fresh_limiter()
    key = "test-shared:scope:1"
    assert all([await limiter.acquire(key, priority=Priority.BATCH) for _ in range(7)])
    assert await limiter.acquire(key, priority=Priority.BATCH) is False
    assert await limiter.acquire(key, priority=Priority.CRITICAL) is True


@pytest.mark.parametrize("priority", [Priority.CRITICAL, Priority.NORMAL, Priority.BATCH])
async def test_no_reserve_policy_is_priority_blind(priority):
    # An empty reserve must reproduce the pre-priority behavior for every lane — no headroom held back.
    register_policy("test-noreserve", RatePolicy(limits=((2, 3600.0),)))
    limiter = _fresh_limiter()
    key = f"test-noreserve:scope:{priority.value}"
    assert [await limiter.acquire(key, priority=priority) for _ in range(3)] == [True, True, False]


def test_reserve_inflated_weight_validation():
    # n plus the reserved floor must fit the limit or it can never be granted — fail loudly, and only
    # for the priority whose reserve makes it unsatisfiable.
    register_policy("test-reserve-weight", RatePolicy(limits=((10, 3600.0),), reserve={Priority.BATCH: 0.3}))
    limiter = _fresh_limiter()
    key = "test-reserve-weight:scope:1"
    with pytest.raises(ValueError):
        limiter.consume_sync(key, 8, priority=Priority.BATCH)  # 8 + floor(0.3*10)=3 -> 11 > 10
    assert limiter.consume_sync(key, 8, priority=Priority.CRITICAL) is True  # 8 + 0 <= 10


@pytest.mark.parametrize("bad_fraction", [-0.1, 1.0, 1.5])
def test_policy_rejects_out_of_range_reserve(bad_fraction):
    # A fraction outside [0, 1) is a config error: 1.0 reserves the whole window and denies forever.
    with pytest.raises(ValueError):
        RatePolicy(limits=((10, 3600.0),), reserve={Priority.BATCH: bad_fraction})
