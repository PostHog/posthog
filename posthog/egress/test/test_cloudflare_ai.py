from django.test import override_settings

from posthog.egress.limiter.policies import resolve_policy


@override_settings(SIGNALS_TYPESAFE_CLOUDFLARE_REQUESTS_PER_MINUTE=20)
def test_cloudflare_ai_budget_is_account_scoped_and_bounded() -> None:
    policy = resolve_policy("cloudflare_ai:account:example")
    assert policy.limits == ((20, 60.0),)
