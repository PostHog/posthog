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


def _install_in_memory_tracer(exporter: InMemorySpanExporter) -> trace.Tracer:
    """Wire up an in-memory span exporter and rebind `posthog.auth.tracer` to use it.

    Returns the prior module-level tracer so the caller can restore it.

    The tracer is taken directly from a fresh `TracerProvider` rather than the global
    one. We can't swap the global with `trace.set_tracer_provider()` because OTel's SDK
    is "set once": when production code calls `initialize_otel()` at startup, any later
    `set_tracer_provider` calls are silently dropped with a warning, so spans created via
    `trace.get_tracer(...)` would still go to the production provider and our exporter
    would see nothing. Going through the provider object directly bypasses the global.
    """
    import posthog.auth as auth_module

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    previous_module_tracer = auth_module.tracer
    auth_module.tracer = provider.get_tracer(auth_module.__name__)

    return previous_module_tracer


def _restore_tracer(previous_module_tracer: trace.Tracer) -> None:
    import posthog.auth as auth_module

    auth_module.tracer = previous_module_tracer


class TestAuthSpans(BaseTest):
    _exporter: InMemorySpanExporter
    _previous_module_tracer: trace.Tracer

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._exporter = InMemorySpanExporter()
        cls._previous_module_tracer = _install_in_memory_tracer(cls._exporter)

    @classmethod
    def tearDownClass(cls):
        _restore_tracer(cls._previous_module_tracer)
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
    def test_authenticate_emits_span(self, _name, build_request, call_authenticate, expected_span_name):
        request = build_request(self.factory)
        call_authenticate(request)

        spans = self._spans_named(expected_span_name)
        assert len(spans) == 1

    def test_personal_api_key_span_records_source_and_hash_mode_on_match(self):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(token),
        )
        request = self.factory.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {token}")

        result = PersonalAPIKeyAuthentication().authenticate(request)
        assert result is not None
        user, _ = result
        assert user == self.user

        parent = self._spans_named("posthog.auth.personal_api_key")
        assert len(parent) == 1
        assert parent[0].attributes["auth.source"] == "header"

        db_lookup = self._spans_named("posthog.auth.personal_api_key.db_lookup")
        assert len(db_lookup) == 1
        assert db_lookup[0].attributes["auth.hash_mode_used"] == "sha256"
        assert db_lookup[0].attributes["auth.modes_tried"] == 1
