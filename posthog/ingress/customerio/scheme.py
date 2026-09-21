"""Customer.io signature scheme, for the DRF adapter path.

Customer.io is the one endpoint that keeps its DRF view: it is team-scoped, its secret comes
from that team's integration row, and it needs no fan-out. So this incarnation contributes a
scheme only -- `posthog.auth.WebhookSignatureAuthentication` does the verifying -- and
declares no provider spec, because nothing dispatches here.
"""

from collections.abc import Callable

from posthog.ingress.verify.schemes import HmacSignature


def build_customerio_scheme(secret_getter: Callable[[], str | None]) -> HmacSignature:
    return HmacSignature(
        secret_getter=secret_getter,
        signature_header="x-cio-signature",
        signed_input="v0_timestamp_body",
        timestamp_header="x-cio-timestamp",
    )
