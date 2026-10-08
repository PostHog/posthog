import time
from dataclasses import replace
from datetime import UTC, datetime

from unittest.mock import Mock, patch

from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.ingress.contracts import (
    DeliveryOwnership,
    DeliveryOwnershipAnswers,
    ProviderSpec,
    WebhookConsumer,
    WebhookDelivery,
)
from posthog.ingress.dispatch.budget import DEFAULT_DELIVERY_BUDGET_SECONDS, DeliveryBudget, delivery_budget_seconds
from posthog.ingress.dispatch.dedup import (
    INGRESS_DEDUP_CACHE_ALIAS,
    DeliveryClaim,
    DeliveryDedup,
    delivery_claim_lease_seconds,
)
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.test import LOCMEM, LOCMEM_CACHES

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


@override_settings(CACHES=LOCMEM_CACHES)
class TestWebhookDispatcher(SimpleTestCase):
    def setUp(self) -> None:
        self.cache = caches[INGRESS_DEDUP_CACHE_ALIAS]
        self.cache.clear()

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
        self.assertIsNone(
            self.cache.get(DeliveryDedup.key(provider="github", consumer="alpha", delivery_id="delivery-1"))
        )
        self.assertTrue(self.cache.get(DeliveryDedup.key(provider="github", consumer="zulu", delivery_id="delivery-1")))

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
        self.assertIsNone(
            self.cache.get(DeliveryDedup.key(provider="github", consumer="alpha", delivery_id="delivery-1"))
        )

    def test_a_cache_outage_fails_open_rather_than_dropping_the_delivery(self) -> None:
        handler = Mock()
        with patch.object(self.cache, "add", side_effect=RuntimeError("cache down")):
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
        self.assertIsNone(
            self.cache.get(DeliveryDedup.key(provider="github", consumer="zulu", delivery_id="delivery-1"))
        )

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


@override_settings(CACHES=LOCMEM_CACHES)
class TestDeliveryDedup(SimpleTestCase):
    def setUp(self) -> None:
        self.cache = caches[INGRESS_DEDUP_CACHE_ALIAS]
        self.cache.clear()
        self.mark = {"provider": "github", "consumer": "alpha", "delivery_id": "delivery-1"}

    def test_a_claim_reads_as_in_flight_to_the_version_that_knows_no_holder_token(self) -> None:
        claim = DeliveryDedup().claim(**self.mark)

        # The deployed version reads every value but this one as done. On a rolling deploy a token
        # in the mark would have an old worker receipt a delivery the new worker can still fail.
        key = DeliveryDedup.key(**self.mark)
        self.assertEqual(self.cache.get(key), "in_progress")
        self.assertEqual(self.cache.get(f"{key}:holder"), claim.token)

    @override_settings(
        CACHES={
            "default": {**LOCMEM, "LOCATION": "default"},
            INGRESS_DEDUP_CACHE_ALIAS: {**LOCMEM, "LOCATION": "ingress_dedup"},
        }
    )
    def test_the_mark_is_written_through_the_dedicated_alias(self) -> None:
        DeliveryDedup().claim(**self.mark)

        # The default alias is replica aware in production, and a replica can still serve a token
        # the primary replaced, which would have a run delete a mark a newer run holds.
        self.assertIsNone(caches["default"].get(DeliveryDedup.key(**self.mark)))
        self.assertEqual(caches[INGRESS_DEDUP_CACHE_ALIAS].get(DeliveryDedup.key(**self.mark)), "in_progress")

    def test_the_mark_reports_the_state_its_holder_left_it_in(self) -> None:
        dedup = DeliveryDedup()

        claim = dedup.claim(**self.mark)
        self.assertEqual(claim.state, DeliveryClaim.CLAIMED)
        # A redelivery that arrives before the first run settles must not read this as done. That
        # run can still raise, and a receipt now stops the provider sending the delivery again.
        self.assertEqual(dedup.claim(**self.mark).state, DeliveryClaim.IN_PROGRESS)

        dedup.release(**self.mark, token=claim.token)
        self.assertEqual(dedup.claim(**self.mark).state, DeliveryClaim.CLAIMED)

        dedup.complete(**self.mark)
        self.assertEqual(dedup.claim(**self.mark).state, DeliveryClaim.DONE)

    @parameterized.expand(
        [
            ("a_flag_from_before_the_state_existed", True, DeliveryClaim.DONE),
            ("a_lease_with_no_holder_key", "in_progress", DeliveryClaim.IN_PROGRESS),
            ("a_settled_mark", "done", DeliveryClaim.DONE),
        ]
    )
    def test_a_mark_this_run_did_not_write_still_dedupes(
        self, _name: str, held: object, expected: DeliveryClaim
    ) -> None:
        self.cache.set(DeliveryDedup.key(**self.mark), held)

        # Marks live for 24 hours, so a rollout meets the ones the previous version wrote. Reading
        # a flag as in flight would cost a receipt for every delivery still holding it, and reading
        # a lease as done would receipt a run that never settled.
        self.assertEqual(DeliveryDedup().claim(**self.mark).state, expected)

    @parameterized.expand(
        [
            ("a_newer_run_holds_the_claim", False, DeliveryClaim.IN_PROGRESS),
            ("a_newer_run_settled_the_mark", True, DeliveryClaim.DONE),
        ]
    )
    def test_a_run_that_lost_its_lease_cannot_drop_the_mark_another_run_holds(
        self, _name: str, settle: bool, expected: DeliveryClaim
    ) -> None:
        dedup = DeliveryDedup()
        stale = dedup.claim(**self.mark)
        # The lease runs out while the first run is still working, and a second run takes the key.
        self.cache.delete(DeliveryDedup.key(**self.mark))
        dedup.claim(**self.mark)
        if settle:
            dedup.complete(**self.mark)

        dedup.release(**self.mark, token=stale.token)

        # Dropping the newer claim would let a third run start beside the two already going, and
        # dropping the done mark would hand finished work back to the provider to redeliver.
        self.assertEqual(dedup.claim(**self.mark).state, expected)

    def test_the_run_the_holder_key_names_cannot_drop_a_settled_mark(self) -> None:
        dedup = DeliveryDedup()
        dedup.claim(**self.mark)
        self.cache.delete(DeliveryDedup.key(**self.mark))
        newer = dedup.claim(**self.mark)
        dedup.complete(**self.mark)

        dedup.release(**self.mark, token=newer.token)

        # Settling does not clear the holder key, so the token still names this run. Releasing on
        # that alone would drop the done mark and hand finished work back to the provider.
        self.assertEqual(dedup.claim(**self.mark).state, DeliveryClaim.DONE)

    @parameterized.expand(
        [
            ("one_expiry_is_reclaimed", 1, DeliveryClaim.CLAIMED),
            ("a_key_that_keeps_vanishing_is_left_in_flight", 2, DeliveryClaim.IN_PROGRESS),
        ]
    )
    def test_a_lease_that_expires_between_the_add_and_the_read_is_never_read_as_done(
        self, _name: str, refusals: int, expected: DeliveryClaim
    ) -> None:
        real_add = self.cache.add
        refused = 0

        def refuse_then_add(*args, **kwargs):
            nonlocal refused
            if refused < refusals:
                refused += 1
                return False
            return real_add(*args, **kwargs)

        with patch.object(self.cache, "add", refuse_then_add):
            claim = DeliveryDedup().claim(**self.mark)

        # A refused add whose follow-up read finds nothing is a lease that ran out under the claim,
        # which is a run that never settled. Reading it as done would receipt work that never
        # finished, and a provider with retry_status would stop redelivering it.
        self.assertEqual(claim.state, expected)

    @parameterized.expand(
        [
            ("an_unsettled_claim_expires_with_its_lease", False, DeliveryClaim.CLAIMED),
            ("a_settled_mark_outlives_the_lease", True, DeliveryClaim.DONE),
        ]
    )
    def test_a_claim_only_outlives_its_lease_once_it_is_settled(
        self, _name: str, settle: bool, expected: DeliveryClaim
    ) -> None:
        start = time.time()

        with patch("time.time", lambda: start):
            DeliveryDedup().claim(**self.mark)
            if settle:
                DeliveryDedup().complete(**self.mark)

        # An in-progress mark nobody settled is what a killed process leaves behind. A provider
        # that redelivers reads it as in flight and is answered a retry status, so a mark that
        # outlived its run would refuse every redelivery until the provider gave up.
        with patch("time.time", lambda: start + delivery_claim_lease_seconds() + 1):
            self.assertEqual(DeliveryDedup().claim(**self.mark).state, expected)


class TestDeliveryOwnership(SimpleTestCase):
    @parameterized.expand(
        [
            ("nobody_declares_one", [], DeliveryOwnershipAnswers()),
            ("every_answer_is_local", [DeliveryOwnership.LOCAL] * 2, DeliveryOwnershipAnswers()),
            (
                "one_elsewhere_decides_the_request",
                [DeliveryOwnership.LOCAL, DeliveryOwnership.ELSEWHERE],
                DeliveryOwnershipAnswers(elsewhere_consumers=("consumer-1",)),
            ),
            (
                "a_lookup_that_raises_leaves_the_others_deciding",
                [RuntimeError("lookup failed"), DeliveryOwnership.ELSEWHERE],
                DeliveryOwnershipAnswers(elsewhere_consumers=("consumer-1",), failed_consumers=("consumer-0",)),
            ),
            (
                "a_lookup_that_raises_is_named_rather_than_read_as_an_answer",
                [RuntimeError("lookup failed")],
                DeliveryOwnershipAnswers(failed_consumers=("consumer-0",)),
            ),
        ]
    )
    def test_the_answers_name_who_forwards_the_request_and_whose_lookup_failed(
        self, _name: str, answers: list, expected: DeliveryOwnershipAnswers
    ) -> None:
        consumers = [
            _consumer(f"consumer-{index}", Mock(), ownership=_ownership(answer)) for index, answer in enumerate(answers)
        ]

        with patch("posthog.ingress.dispatch.dispatcher.capture_exception"):
            self.assertEqual(_dispatcher(consumers).ownership_of(_delivery()), expected)

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
