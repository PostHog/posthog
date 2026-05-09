from posthog.test.base import BaseTest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.auth import JwtAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestAuthSpans(BaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(cls._exporter))
        cls._previous_provider = trace._TRACER_PROVIDER
        trace._TRACER_PROVIDER = provider

        import posthog.auth as auth_module

        cls._previous_module_tracer = auth_module.tracer
        auth_module.tracer = trace.get_tracer(auth_module.__name__)

    @classmethod
    def tearDownClass(cls):
        import posthog.auth as auth_module

        auth_module.tracer = cls._previous_module_tracer
        trace._TRACER_PROVIDER = cls._previous_provider
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._exporter.clear()
        self.factory = APIRequestFactory()

    def _spans_named(self, name):
        return [s for s in self._exporter.get_finished_spans() if s.name == name]

    def test_personal_api_key_span_when_no_key_in_request(self):
        request = self.factory.get("/api/users/@me/")
        result = PersonalAPIKeyAuthentication().authenticate(request)
        assert result is None

        spans = self._spans_named("posthog.auth.personal_api_key")
        assert len(spans) == 1
        assert spans[0].attributes["auth.matched"] is False
        assert "auth.source" not in spans[0].attributes

    def test_personal_api_key_span_when_key_matches(self):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
        )
        request = self.factory.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {token}")

        user, _ = PersonalAPIKeyAuthentication().authenticate(request)
        assert user == self.user

        parent = self._spans_named("posthog.auth.personal_api_key")
        assert len(parent) == 1
        assert parent[0].attributes["auth.matched"] is True
        assert parent[0].attributes["auth.source"] == "header"

        db_lookup = self._spans_named("posthog.auth.personal_api_key.db_lookup")
        assert len(db_lookup) == 1
        assert db_lookup[0].attributes["auth.matched"] is True
        assert db_lookup[0].attributes["auth.hash_mode_used"] == "sha256"
        assert db_lookup[0].attributes["auth.modes_tried"] == 1

    def test_jwt_span_when_no_authorization_header(self):
        request = self.factory.get("/api/users/@me/")
        result = JwtAuthentication.authenticate(request)
        assert result is None

        spans = self._spans_named("posthog.auth.jwt")
        assert len(spans) == 1
        assert spans[0].attributes["auth.matched"] is False

    def test_session_span_when_no_session(self):
        django_request = self.factory.get("/api/users/@me/")
        request = Request(django_request)
        request._authenticator = None  # type: ignore[attr-defined]
        SessionAuthentication().authenticate(request)

        spans = self._spans_named("posthog.auth.session")
        assert len(spans) == 1
        assert spans[0].attributes["auth.matched"] is False
