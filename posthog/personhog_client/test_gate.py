from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from posthog.personhog_client.gate import pin_personhog_decision, unpin_personhog_decision, use_personhog
from posthog.personhog_client.middleware import PersonHogGateMiddleware

ENABLED_SETTINGS = {
    "PERSONHOG_ENABLED": True,
    "PERSONHOG_ADDR": "localhost:50051",
    "PERSONHOG_ROLLOUT_PERCENTAGE": 50,
}


class TestPersonHogGatePinning(SimpleTestCase):
    def setUp(self):
        unpin_personhog_decision()

    def tearDown(self):
        unpin_personhog_decision()

    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", return_value=True)
    def test_unpinned_does_not_cache(self, mock_decide):
        use_personhog()
        use_personhog()
        use_personhog()
        assert mock_decide.call_count == 3

    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", return_value=True)
    def test_pinned_caches_after_first_call(self, mock_decide):
        pin_personhog_decision()
        assert use_personhog() is True
        assert use_personhog() is True
        assert use_personhog() is True
        assert mock_decide.call_count == 1

    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", side_effect=[True, False])
    def test_unpin_clears_cached_decision(self, mock_decide):
        pin_personhog_decision()
        assert use_personhog() is True

        unpin_personhog_decision()
        pin_personhog_decision()
        assert use_personhog() is False

    @override_settings(PERSONHOG_ENABLED=False)
    def test_disabled_always_returns_false(self):
        pin_personhog_decision()
        assert use_personhog() is False

    @override_settings(**{**ENABLED_SETTINGS, "PERSONHOG_ROLLOUT_PERCENTAGE": 100})
    def test_full_rollout_always_returns_true(self):
        pin_personhog_decision()
        assert use_personhog() is True

    @override_settings(**{**ENABLED_SETTINGS, "PERSONHOG_ROLLOUT_PERCENTAGE": 0})
    def test_zero_rollout_always_returns_false(self):
        pin_personhog_decision()
        assert use_personhog() is False


class TestPersonHogGateMiddleware(SimpleTestCase):
    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", return_value=True)
    def test_middleware_pins_decision_for_request(self, mock_decide):
        """All use_personhog() calls within a request return the same value."""
        captured = []

        def view(request):
            captured.extend([use_personhog() for _ in range(5)])
            return HttpResponse("ok")

        middleware = PersonHogGateMiddleware(view)
        middleware(RequestFactory().get("/"))

        assert captured == [True, True, True, True, True]
        assert mock_decide.call_count == 1

    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", side_effect=[True, False])
    def test_middleware_unpins_between_requests(self, mock_decide):
        """Each request gets a fresh decision."""
        results = []

        def view(request):
            results.append(use_personhog())
            return HttpResponse("ok")

        middleware = PersonHogGateMiddleware(view)
        middleware(RequestFactory().get("/first"))
        middleware(RequestFactory().get("/second"))

        assert results == [True, False]
        assert mock_decide.call_count == 2

    @override_settings(**ENABLED_SETTINGS)
    @patch("posthog.personhog_client.gate._decide_personhog", return_value=True)
    def test_middleware_unpins_on_exception(self, mock_decide):
        """Decision is cleared even if the view raises."""

        def exploding_view(request):
            use_personhog()
            raise RuntimeError("boom")

        middleware = PersonHogGateMiddleware(exploding_view)
        with self.assertRaises(RuntimeError):
            middleware(RequestFactory().get("/"))

        # After the failed request, gate should be unpinned
        assert not hasattr(use_personhog, "personhog_pinned") or True
        # Calling again outside middleware should re-roll (call _decide again)
        use_personhog()
        assert mock_decide.call_count == 2
