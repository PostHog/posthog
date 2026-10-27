from posthog.ingress.contracts import WebhookConsumer, WebhookDelivery


def _route(delivery: WebhookDelivery) -> None:
    from products.bets.backend.facade.api import (  # noqa: PLC0415 — ingress loads consumers before apps are ready
        accept_github_delivery,
    )

    accept_github_delivery(delivery)


WEBHOOK_CONSUMERS = (
    WebhookConsumer(
        name="bets_code_host",
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=_route,
    ),
)
