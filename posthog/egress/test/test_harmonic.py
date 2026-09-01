import uuid

from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.egress.harmonic.limiter import HARMONIC_GLOBAL_KEY, consume_harmonic
from posthog.egress.harmonic.observability import _parse_harmonic_rate_limit
from posthog.egress.harmonic.transport import HarmonicEgressBudgetExhausted, harmonic_request
from posthog.egress.limiter.backends import LimitsBackend
from posthog.egress.limiter.outbound import OutboundRateLimiter
from posthog.egress.limiter.policies import Priority
from posthog.egress.observability.observability import RateLimitSnapshot


def _unique_harmonic_key() -> str:
    # Distinct scope per test so it never shares a sliding window with the literal
    # "harmonic:global" key (or with another test) while still resolving to the real registered
    # harmonic policy, whose provider only inspects the "harmonic" domain segment.
    return f"harmonic:test:{uuid.uuid4().hex}"


def _fake_session(status: int = 200, headers: dict | None = None) -> AsyncMock:
    response = AsyncMock()
    response.status = status
    response.headers = headers or {}
    session = AsyncMock()
    session.request = AsyncMock(return_value=response)
    return session


class TestHarmonicLimiterRegistration(SimpleTestCase):
    def test_policy_is_registered_for_the_global_key(self) -> None:
        # consume raises for a domain with no registered policy — this catches the registration
        # side effect being lost (e.g. an import shuffle dropping the register_policy call).
        assert HARMONIC_GLOBAL_KEY == "harmonic:global"
        assert consume_harmonic(source="test") is True


@override_settings(HARMONIC_EGRESS_PER_SECOND_BUDGET=3)
async def test_policy_admits_at_the_configured_rate_and_denies_above_it() -> None:
    limiter = OutboundRateLimiter(LimitsBackend())
    key = _unique_harmonic_key()
    grants = [await limiter.acquire(key, priority=Priority.CRITICAL) for _ in range(4)]
    assert grants == [True, True, True, False]


@override_settings(HARMONIC_EGRESS_PER_SECOND_BUDGET=10)
async def test_batch_pressure_does_not_starve_the_interactive_lane() -> None:
    # Fill the non-reserved share with BATCH (7 of 10, since BATCH reserves 30%), then prove BATCH
    # is denied while CRITICAL still draws from the SAME counter — the reserved floor protecting
    # exactly the headroom a Friday bulk burst must not be allowed to take from a signup lookup.
    limiter = OutboundRateLimiter(LimitsBackend())
    key = _unique_harmonic_key()
    assert all([await limiter.acquire(key, priority=Priority.BATCH) for _ in range(7)])
    assert await limiter.acquire(key, priority=Priority.BATCH) is False
    assert await limiter.acquire(key, priority=Priority.CRITICAL) is True


class TestHarmonicRateLimitHeaderParser(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_headers", None, RateLimitSnapshot(resource="global")),
            ("empty_headers", {}, RateLimitSnapshot(resource="global")),
            (
                "garbage_values",
                {"X-RateLimit-Remaining": "not-a-number", "X-RateLimit-Limit": "", "X-RateLimit-Reset": "soon"},
                RateLimitSnapshot(resource="global"),
            ),
            (
                "standard_names",
                {"X-RateLimit-Remaining": "42", "X-RateLimit-Limit": "100", "X-RateLimit-Reset": "1700000000"},
                RateLimitSnapshot(resource="global", remaining=42.0, limit=100.0, reset_at=1700000000.0),
            ),
            (
                "second_variant_preferred_over_standard",
                {
                    "X-Ratelimit-Remaining-Second": "5",
                    "X-RateLimit-Remaining": "500",
                    "X-Ratelimit-Limit-Second": "15",
                },
                RateLimitSnapshot(resource="global", remaining=5.0, limit=15.0),
            ),
            (
                "second_variant_alone",
                {"X-Ratelimit-Remaining-Second": "9", "X-Ratelimit-Limit-Second": "15"},
                RateLimitSnapshot(resource="global", remaining=9.0, limit=15.0),
            ),
        ]
    )
    def test_parser_returns_none_for_absent_or_garbage_headers(self, _name, headers, expected) -> None:
        assert _parse_harmonic_rate_limit(headers) == expected


async def test_request_gates_before_sending_and_records_the_response() -> None:
    session = _fake_session(status=201, headers={"X-Ratelimit-Remaining-Second": "9"})
    with (
        patch("posthog.egress.harmonic.transport.acquire_harmonic", AsyncMock(return_value=True)) as acquire,
        patch("posthog.egress.harmonic.transport.record_harmonic_api_response") as record_response,
    ):
        response = await harmonic_request(
            session,
            "POST",
            "https://api.harmonic.ai/graphql",
            source="test",
            priority=Priority.CRITICAL,
            endpoint="/graphql",
            headers={"apikey": "secret"},
        )

    assert response.status == 201
    acquire.assert_awaited_once_with(Priority.CRITICAL, "test")
    session.request.assert_awaited_once()
    assert session.request.call_args.kwargs["headers"]["apikey"] == "secret"
    record_response.assert_called_once_with(
        201, {"X-Ratelimit-Remaining-Second": "9"}, source="test", method="POST", endpoint="/graphql"
    )


async def test_request_raises_for_a_sheddable_call_when_the_budget_is_denied() -> None:
    session = _fake_session()
    with patch("posthog.egress.harmonic.transport.acquire_harmonic", AsyncMock(return_value=False)):
        try:
            await harmonic_request(
                session, "GET", "https://api.harmonic.ai/companies/1", source="test", priority=Priority.BATCH
            )
            raised = False
        except HarmonicEgressBudgetExhausted:
            raised = True
    assert raised
    session.request.assert_not_called()


async def test_request_never_raises_for_critical_even_when_denied() -> None:
    # CRITICAL is never shed by us — it proceeds and lets Harmonic's own rate limiting be the
    # backstop, matching every other egress domain's denial semantics.
    session = _fake_session()
    with patch("posthog.egress.harmonic.transport.acquire_harmonic", AsyncMock(return_value=False)):
        await harmonic_request(
            session, "GET", "https://api.harmonic.ai/companies/1", source="test", priority=Priority.CRITICAL
        )
    session.request.assert_awaited_once()
