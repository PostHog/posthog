from posthog.test.base import BaseTest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from parameterized import parameterized
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.auth import JwtAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


def _install_in_memory_tracer(
    exporter: InMemorySpanExporter,
) -> tuple[trace.TracerProvider, trace.Tracer]:
    """Wire up an in-memory span exporter and rebind the auth module's tracer to it.

    Returns the prior provider and prior module-level tracer so the caller can restore them.
    The module-level rebind is necessary because posthog.auth grabs its tracer at import
    time, so swapping the global TracerProvider alone isn't enough — its proxy is already
    bound to whatever provider existed at import.
    """
    import posthog.auth as auth_module

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    previous_provider = trace.get_tracer_provider()
    trace.set_tracer_provider(provider)

    previous_module_tracer = auth_module.tracer
    auth_module.tracer = trace.get_tracer(auth_module.__name__)

    return previous_provider, previous_module_tracer


def _restore_tracer(previous_provider: trace.TracerProvider, previous_module_tracer: trace.Tracer) -> None:
    import posthog.auth as auth_module

    auth_module.tracer = previous_module_tracer
    trace.set_tracer_provider(previous_provider)


class TestAuthSpans(BaseTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._exporter = InMemorySpanExporter()
        cls._previous_provider, cls._previous_module_tracer = _install_in_memory_tracer(cls._exporter)

    @classmethod
    def tearDownClass(cls):
        _restore_tracer(cls._previous_provider, cls._previous_module_tracer)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self._exporter.clear()
        self.factory = APIRequestFactory()

    def _spans_named(self, name):
        return [s for s in self._exporter.get_finished_spans() if s.name == name]

    @parameterized.expand(
        [
            (
                "personal_api_key_no_key",
                lambda factory: factory.get("/api/users/@me/"),
                lambda req: PersonalAPIKeyAuthentication().authenticate(req),
                "posthog.auth.personal_api_key",
            ),
            (
                "jwt_no_authorization_header",
                lambda factory: factory.get("/api/users/@me/"),
                lambda req: JwtAuthentication.authenticate(req),
                "posthog.auth.jwt",
            ),
            (
                "session_no_session",
                lambda factory: Request(factory.get("/api/users/@me/")),
                lambda req: SessionAuthentication().authenticate(req),
                "posthog.auth.session",
            ),
        ]
    )
    def test_authenticate_unmatched_emits_span(self, _name, build_request, call_authenticate, expected_span_name):
        request = build_request(self.factory)
        result = call_authenticate(request)
        assert result is None

        spans = self._spans_named(expected_span_name)
        assert len(spans) == 1
        assert spans[0].attributes["auth.matched"] is False

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
