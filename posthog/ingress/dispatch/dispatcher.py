"""Fan one delivery out to its consumers, inside one wall-clock budget."""

import time

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.ingress.contracts import DeliveryOwnership, WebhookConsumer, WebhookDelivery
from posthog.ingress.dispatch.budget import DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.dedup import DeliveryDedup
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.observability.metrics import observe_consumer_duration, observe_consumer_run, observe_ownership

logger = structlog.get_logger(__name__)


class WebhookDispatcher:
    """Runs the consumers registered for a delivery, in name order.

    Each consumer is isolated: one raising is logged and captured but never stops another,
    and never changes the response the provider already earned by signing the request.
    """

    def __init__(
        self,
        registry: ConsumerRegistry,
        *,
        dedup: DeliveryDedup | None = None,
        budget_seconds: float | None = None,
    ) -> None:
        self._registry = registry
        self._dedup = dedup if dedup is not None else DeliveryDedup()
        self._budget_seconds = budget_seconds

    def _run(self, consumer: WebhookConsumer, delivery: WebhookDelivery) -> None:
        # A consumer that opted out of dedup claims and releases nothing, so a redelivery always
        # reaches it. Skipping is not an outcome of its own: it simply runs.
        delivery_id = delivery.delivery_id if consumer.dedup else None
        if delivery_id and not self._dedup.claim(
            provider=delivery.provider, consumer=consumer.name, delivery_id=delivery_id
        ):
            logger.info(
                "ingress_consumer_deduped",
                provider=delivery.provider,
                consumer=consumer.name,
                event_type=delivery.event_type,
                delivery_id=delivery.delivery_id,
            )
            observe_consumer_run(provider=delivery.provider, consumer=consumer.name, outcome="deduped")
            return

        started = time.monotonic()
        try:
            consumer.handler(delivery)
        except Exception as error:
            logger.exception(
                "ingress_consumer_failed",
                provider=delivery.provider,
                consumer=consumer.name,
                event_type=delivery.event_type,
                delivery_id=delivery.delivery_id,
            )
            capture_exception(error)
            if delivery_id:
                self._dedup.release(provider=delivery.provider, consumer=consumer.name, delivery_id=delivery_id)
            observe_consumer_run(provider=delivery.provider, consumer=consumer.name, outcome="failed")
        else:
            observe_consumer_run(provider=delivery.provider, consumer=consumer.name, outcome="succeeded")
        finally:
            observe_consumer_duration(
                provider=delivery.provider, consumer=consumer.name, seconds=time.monotonic() - started
            )

    def _ask_ownership(self, consumer: WebhookConsumer, delivery: WebhookDelivery) -> DeliveryOwnership:
        if consumer.ownership is None:
            return DeliveryOwnership.UNDECIDED
        try:
            answer = consumer.ownership(delivery)
        except Exception as error:
            # Isolated like a handler is: a consumer that cannot answer must not cost the delivery
            # the receipt it already earned by signing, nor stop another consumer from answering.
            logger.exception(
                "ingress_ownership_failed",
                provider=delivery.provider,
                consumer=consumer.name,
                event_type=delivery.event_type,
                delivery_id=delivery.delivery_id,
            )
            capture_exception(error)
            observe_ownership(provider=delivery.provider, consumer=consumer.name, outcome="failed")
            return DeliveryOwnership.UNDECIDED
        observe_ownership(provider=delivery.provider, consumer=consumer.name, outcome=answer.value)
        return answer

    def ownership_of(self, delivery: WebhookDelivery) -> tuple[DeliveryOwnership, tuple[str, ...]]:
        """Where this delivery's resource lives, and which consumers said it lives elsewhere.

        Any one consumer answering `ELSEWHERE` is enough to forward the request, because the
        forward is the whole request rather than one consumer's share of it. A `LOCAL` answer
        changes nothing: local dispatch runs either way.
        """
        answers: list[DeliveryOwnership] = []
        elsewhere: list[str] = []
        for consumer in self._registry.consumers_for(
            provider=delivery.provider, app=delivery.app, event_type=delivery.event_type
        ):
            if consumer.ownership is None:
                continue
            answer = self._ask_ownership(consumer, delivery)
            answers.append(answer)
            if answer is DeliveryOwnership.ELSEWHERE:
                elsewhere.append(consumer.name)

        if elsewhere:
            return DeliveryOwnership.ELSEWHERE, tuple(elsewhere)
        if DeliveryOwnership.LOCAL in answers:
            return DeliveryOwnership.LOCAL, ()
        return DeliveryOwnership.UNDECIDED, ()

    def dispatch(self, delivery: WebhookDelivery, *, budget: DeliveryBudget | None = None) -> None:
        """Run this delivery's consumers.

        The caller passes a budget when one request carries several deliveries, so the request
        is bounded rather than each delivery separately.
        """
        if not self._registry.declares(provider=delivery.provider, app=delivery.app):
            # A verified delivery for an app no incarnation declares is a wiring mistake: the
            # endpoint answers its usual receipt and runs nothing at all.
            logger.error(
                "ingress_delivery_undeclared_app",
                provider=delivery.provider,
                app=delivery.app,
                event_type=delivery.event_type,
            )
            return

        consumers = self._registry.consumers_for(
            provider=delivery.provider, app=delivery.app, event_type=delivery.event_type
        )
        if not consumers:
            logger.info(
                "ingress_delivery_without_consumers",
                provider=delivery.provider,
                app=delivery.app,
                event_type=delivery.event_type,
            )
            return

        logger.info(
            "ingress_delivery_dispatch",
            provider=delivery.provider,
            app=delivery.app,
            event_type=delivery.event_type,
            delivery_id=delivery.delivery_id,
            consumers=[consumer.name for consumer in consumers],
        )

        if budget is None:
            budget = DeliveryBudget(
                self._budget_seconds if self._budget_seconds is not None else delivery_budget_seconds()
            )
        for index, consumer in enumerate(consumers):
            if budget.is_spent():
                skipped = consumers[index:]
                # No dedup mark for these, so the provider's redelivery reaches them.
                logger.warning(
                    "ingress_delivery_budget_exceeded",
                    provider=delivery.provider,
                    app=delivery.app,
                    event_type=delivery.event_type,
                    delivery_id=delivery.delivery_id,
                    skipped=[pending.name for pending in skipped],
                )
                for pending in skipped:
                    observe_consumer_run(provider=delivery.provider, consumer=pending.name, outcome="budget_exceeded")
                return
            self._run(consumer, delivery)
