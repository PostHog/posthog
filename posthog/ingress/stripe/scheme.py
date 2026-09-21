"""Stripe partner-provisioning signature scheme, for the DRF adapter path.

The provisioning endpoints are a signed request/response API rather than a webhook: Stripe
calls PostHog and reads the JSON answer. So this incarnation contributes a scheme only -- the
DRF views keep their own check ordering and their own error envelope -- and declares no
provider spec, because nothing dispatches here.
"""

from collections.abc import Callable

from posthog.ingress.verify.schemes import StripeSignature


def build_stripe_provisioning_scheme(
    secret_getter: Callable[[], str | None],
    *,
    timestamp_max_age_seconds: int,
) -> StripeSignature:
    return StripeSignature(secret_getter=secret_getter, timestamp_max_age_seconds=timestamp_max_age_seconds)
