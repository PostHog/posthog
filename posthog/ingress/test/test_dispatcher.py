from dataclasses import replace
from datetime import UTC, datetime

from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.contracts import DeliveryOwnership, ProviderSpec, WebhookConsumer, WebhookDelivery
from posthog.ingress.dispatch.budget import DEFAULT_DELIVERY_BUDGET_SECONDS, DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.dedup import DeliveryClaim, DeliveryDedup
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.registry import ConsumerRegistry

SPEC = ProviderSpec(provider="github", app="posthog", event_types=frozenset({"pull_request"}))


def _delivery(delivery_id: str | None = "delivery-1") -> WebhookDelivery:
    return WebhookDelivery(
        provider="github",
        app="posthog",
        delivery_id=delivery_id,
        event_type="pull_request",
        payload={},
        received_at=datetime(2026, 9, 14, tzinfo=UTC),
        context={},
    )


def _consumer(name: str, handler, *, dedup: bool = True, ownership=None) -> WebhookConsumer:
    return WebhookConsumer(
        name=name,
        provider="github",
        app="posthog",
        event_types=frozenset({"pull_request"}),
        handler=handler,
        dedup=dedup,
        ownership=ownership,
    )


def _ownership(answer):
    def lookup(delivery: WebhookDelivery) -> DeliveryOwnership:
        if isinstance(answer, Exception):
            raise answer
        return answer

    return lookup


def _dispatcher(consumers: list[WebhookConsumer], *, budget_seconds: float | None = None) -> WebhookDispatcher:
    return WebhookDispatcher(
        ConsumerRegistry(providers=[SPEC], consumers=consumers),
        budget_seconds=budget_seconds,
    )


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestWebhookDispatcher(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            ("an_app_no_incarnation_declares", "other", "pull_request"),
            ("an_event_type_no_consumer_registered_for", "posthog", "issues"),
        ]
    )
    def test_a_delivery_with_nothing_to_run_names_no_unaccepted_consumer(
        self, _name: str, app: str, event_type: str
    ) -> None:
        dispatcher = _dispatcher([_consumer("alpha", Mock())])

        dispatched = dispatcher.dispatch(replace(_delivery(), app=app, event_type=event_type))

        # Nothing ran, so nothing failed: a provider that redelivers must not be asked to send
        # an event no consumer wants all over again.
        self.assertEqual(dispatched.unaccepted_consumers, ())

    def test_runs_consumers_in_name_order(self) -> None:
        ran: list[str] = []
        consumers = [
            _consumer("zulu", lambda delivery: ran.append("zulu")),
            _consumer("alpha", lambda delivery: ran.append("alpha")),
        ]

        _dispatcher(consumers).dispatch(_delivery())

        self.assertEqual(ran, ["alpha", "zulu"])

    def test_one_failing_consumer_does_not_stop_the_others(self) -> None:
        failing = Mock(side_effect=RuntimeError("consumer failed"))
        surviving = Mock()

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception") as capture:
            _dispatcher([_consumer("alpha", failing), _consumer("zulu", surviving)]).dispatch(_delivery())

        surviving.assert_called_once()
        capture.assert_called_once()

    def test_dedup_marks_before_the_run_and_releases_when_the_consumer_raises(self) -> None:
        failing = Mock(side_effect=RuntimeError("consumer failed"))
        succeeding = Mock()
        dispatcher = _dispatcher([_consumer("alpha", failing), _consumer("zulu", succeeding)])

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception"):
            dispatched = dispatcher.dispatch(_delivery())

        self.assertEqual(dispatched.unaccepted_consumers, ("alpha",))
        self.assertIsNone(cache.get(DeliveryDedup.key(provider="github", consumer="alpha", delivery_id="delivery-1")))
        self.assertTrue(cache.get(DeliveryDedup.key(provider="github", consumer="zulu", delivery_id="delivery-1")))

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception"):
            dispatched = dispatcher.dispatch(_delivery())

        self.assertEqual(failing.call_count, 2)
        self.assertEqual(succeeding.call_count, 1)
        # The deduped one accepted the earlier delivery, so only the failure is named again.
        self.assertEqual(dispatched.unaccepted_consumers, ("alpha",))

    def test_a_provider_without_a_delivery_id_skips_dedup(self) -> None:
        handler = Mock()
        dispatcher = _dispatcher([_consumer("alpha", handler)])

        dispatcher.dispatch(_delivery(delivery_id=None))
        dispatcher.dispatch(_delivery(delivery_id=None))

        self.assertEqual(handler.call_count, 2)

    def test_a_consumer_that_opted_out_of_dedup_runs_on_every_redelivery(self) -> None:
        opted_out = Mock()
        sibling = Mock()
        dispatcher = _dispatcher([_consumer("alpha", opted_out, dedup=False), _consumer("zulu", sibling)])

        dispatcher.dispatch(_delivery())
        dispatcher.dispatch(_delivery())

        self.assertEqual(opted_out.call_count, 2)
        self.assertEqual(sibling.call_count, 1)
        self.assertIsNone(cache.get(DeliveryDedup.key(provider="github", consumer="alpha", delivery_id="delivery-1")))

    def test_a_cache_outage_fails_open_rather_than_dropping_the_delivery(self) -> None:
        handler = Mock()
        with patch.object(cache, "add", side_effect=RuntimeError("cache down")):
            _dispatcher([_consumer("alpha", handler)]).dispatch(_delivery())

        handler.assert_called_once()

    def test_a_spent_budget_skips_the_rest_without_marking_them_deduped(self) -> None:
        elapsed = {"seconds": 0.0}

        def spend_the_budget(delivery: WebhookDelivery) -> None:
            elapsed["seconds"] += 30.0

        skipped = Mock()
        dispatcher = _dispatcher([_consumer("alpha", spend_the_budget), _consumer("zulu", skipped)], budget_seconds=8)

        with (
            patch("time.monotonic", lambda: elapsed["seconds"]),
            patch("posthog.ingress.dispatch.dispatcher.observe_consumer_run") as observe,
        ):
            dispatched = dispatcher.dispatch(_delivery())

        skipped.assert_not_called()
        self.assertEqual(dispatched.unaccepted_consumers, ("zulu",))
        self.assertIn(
            {"provider": "github", "consumer": "zulu", "outcome": "budget_exceeded"},
            [call.kwargs for call in observe.call_args_list],
        )
        self.assertIsNone(cache.get(DeliveryDedup.key(provider="github", consumer="zulu", delivery_id="delivery-1")))

        dispatcher_with_room = _dispatcher([_consumer("zulu", skipped)], budget_seconds=10)
        dispatcher_with_room.dispatch(_delivery())
        skipped.assert_called_once()

    def test_a_budget_passed_in_spans_every_delivery_of_one_request(self) -> None:
        elapsed = {"seconds": 0.0}

        def spend_the_budget(delivery: WebhookDelivery) -> None:
            elapsed["seconds"] += 30.0

        second = Mock()
        dispatcher = _dispatcher([_consumer("alpha", spend_the_budget)])

        with patch("time.monotonic", lambda: elapsed["seconds"]):
            budget = DeliveryBudget(8)
            dispatcher.dispatch(_delivery(delivery_id="delivery-1"), budget=budget)
            _dispatcher([_consumer("alpha", second)]).dispatch(_delivery(delivery_id="delivery-2"), budget=budget)

        second.assert_not_called()


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestDeliveryDedup(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.mark = {"provider": "github", "consumer": "alpha", "delivery_id": "delivery-1"}

    def test_the_mark_reports_the_state_its_holder_left_it_in(self) -> None:
        dedup = DeliveryDedup()

        self.assertEqual(dedup.claim(**self.mark), DeliveryClaim.CLAIMED)
        # A redelivery that arrives before the first run settles must not read this as done. That
        # run can still raise, and a receipt now stops the provider sending the delivery again.
        self.assertEqual(dedup.claim(**self.mark), DeliveryClaim.IN_PROGRESS)

        dedup.complete(**self.mark)
        self.assertEqual(dedup.claim(**self.mark), DeliveryClaim.DONE)

        dedup.release(**self.mark)
        self.assertEqual(dedup.claim(**self.mark), DeliveryClaim.CLAIMED)

    def test_a_mark_written_before_the_state_existed_still_dedupes(self) -> None:
        cache.set(DeliveryDedup.key(**self.mark), True)

        # Marks live for 24 hours, so a rollout meets the old ones. Reading one as in flight would
        # cost a receipt for every delivery still holding it.
        self.assertEqual(DeliveryDedup().claim(**self.mark), DeliveryClaim.DONE)


class TestDeliveryOwnership(SimpleTestCase):
    @parameterized.expand(
        [
            ("nobody_declares_one", [], DeliveryOwnership.UNDECIDED, ()),
            ("every_answer_is_local", [DeliveryOwnership.LOCAL] * 2, DeliveryOwnership.LOCAL, ()),
            (
                "one_elsewhere_decides_the_request",
                [DeliveryOwnership.LOCAL, DeliveryOwnership.ELSEWHERE],
                DeliveryOwnership.ELSEWHERE,
                ("consumer-1",),
            ),
            (
                "a_lookup_that_raises_leaves_the_others_deciding",
                [RuntimeError("lookup failed"), DeliveryOwnership.ELSEWHERE],
                DeliveryOwnership.ELSEWHERE,
                ("consumer-1",),
            ),
            (
                "a_lookup_that_raises_alone_is_undecided",
                [RuntimeError("lookup failed")],
                DeliveryOwnership.UNDECIDED,
                (),
            ),
        ]
    )
    def test_any_consumer_answering_elsewhere_forwards_the_request(
        self, _name: str, answers: list, expected: DeliveryOwnership, expected_names: tuple[str, ...]
    ) -> None:
        consumers = [
            _consumer(f"consumer-{index}", Mock(), ownership=_ownership(answer)) for index, answer in enumerate(answers)
        ]

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception"):
            self.assertEqual(_dispatcher(consumers).ownership_of(_delivery()), (expected, expected_names))

    def test_a_consumer_without_an_ownership_lookup_is_never_asked(self) -> None:
        asked = Mock(return_value=DeliveryOwnership.LOCAL)
        consumers = [_consumer("alpha", Mock()), _consumer("zulu", Mock(), ownership=asked)]

        _dispatcher(consumers).ownership_of(_delivery())

        asked.assert_called_once()


class TestDeliveryBudgetSeconds(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero_would_skip_every_consumer", 0, DEFAULT_DELIVERY_BUDGET_SECONDS),
            ("negative_would_skip_every_consumer", -1, DEFAULT_DELIVERY_BUDGET_SECONDS),
            ("infinity_would_remove_the_backstop", float("inf"), DEFAULT_DELIVERY_BUDGET_SECONDS),
            ("nan_would_remove_the_backstop", float("nan"), DEFAULT_DELIVERY_BUDGET_SECONDS),
            ("a_positive_finite_value_is_honored", 2.5, 2.5),
        ]
    )
    def test_a_misconfigured_setting_falls_back_to_the_default(
        self, _name: str, configured: float, expected: float
    ) -> None:
        with override_settings(INGRESS_DELIVERY_BUDGET_SECONDS=configured):
            self.assertEqual(delivery_budget_seconds(), expected)
