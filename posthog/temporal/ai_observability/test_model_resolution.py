import uuid

import pytest

from django.db import OperationalError, connection

from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team
from posthog.temporal.ai_observability.model_resolution import ExplicitModelSpec, UnconfiguredModelSpec, model_spec

from products.ai_observability.backend.models.evaluation_config import EvaluationConfig
from products.ai_observability.backend.models.provider_keys import LLMProviderKey


@pytest.fixture
def team():
    organization = Organization.objects.create(name="Test Org")
    return Team.objects.create(organization=organization, name="Test Team")


def _key(team, provider, state=LLMProviderKey.State.OK):
    return LLMProviderKey.objects.create(
        team=team,
        provider=provider,
        name=f"{provider} key",
        state=state,
        encrypted_config={"api_key": "sk-test"},
    )


def _error_type(exc_info):
    return exc_info.value.details[0]["error_type"]


# Fails the first SELECT against `table` and passes every other query through. The statement never
# reaches Postgres, so the retry has to re-issue the real read instead of reusing whatever the
# failed attempt left on the instance.
class _FailFirstRead:
    def __init__(self, table):
        self.table = table
        self.reads = 0

    def __call__(self, execute, sql, params, many, context):
        if sql.lstrip().startswith("SELECT") and self.table in sql:
            self.reads += 1
            if self.reads == 1:
                raise OperationalError("query_wait_timeout")
        return execute(sql, params, many, context)


class TestModelSpecFactory:
    def test_null_config_returns_unconfigured_spec(self):
        assert isinstance(model_spec(None), UnconfiguredModelSpec)

    def test_present_config_returns_explicit_spec(self):
        spec = model_spec({"provider": "openai", "model": "gpt-5-mini", "provider_key_id": None})
        assert spec == ExplicitModelSpec(provider="openai", model="gpt-5-mini", provider_key_id=None)


@pytest.mark.django_db
class TestExplicitModelSpec:
    def test_byok_resolves_to_pinned_key_and_touches_last_used(self, team):
        key = _key(team, "anthropic")
        resolved = ExplicitModelSpec("anthropic", "claude-opus-4-8", str(key.id)).resolve(team.id)

        assert resolved.provider == "anthropic"
        assert resolved.model == "claude-opus-4-8"
        assert resolved.provider_key == key
        assert resolved.is_byok
        key.refresh_from_db()
        assert key.last_used_at is not None

    def test_byok_key_lookup_recovers_from_transient_operational_error(self, team):
        # A dropped pooled connection surfaces as a transient OperationalError, which must not
        # fail the whole eval run when a second read on a fresh connection would succeed.
        key = _key(team, "anthropic")
        fail_first = _FailFirstRead(LLMProviderKey._meta.db_table)

        with connection.execute_wrapper(fail_first):
            resolved = ExplicitModelSpec("anthropic", "claude-opus-4-8", str(key.id)).resolve(team.id)

        assert resolved.provider_key == key
        assert fail_first.reads == 2

    def test_byok_missing_key_raises_key_not_found(self, team):
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", str(uuid.uuid4())).resolve(team.id)
        assert _error_type(exc_info) == "key_not_found"

    def test_byok_invalid_key_raises_key_invalid(self, team):
        key = _key(team, "openai", state=LLMProviderKey.State.INVALID)
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", str(key.id)).resolve(team.id)
        assert _error_type(exc_info) == "key_invalid"

    @pytest.mark.parametrize(
        "state,expected_phrase",
        [
            (LLMProviderKey.State.UNKNOWN, "has not been validated yet"),
            (LLMProviderKey.State.INVALID, "was rejected by the provider"),
            (LLMProviderKey.State.ERROR, "last failed with a provider error"),
        ],
    )
    def test_unusable_key_message_names_the_actual_state(self, team, state, expected_phrase):
        # Every non-OK state used to report "This API key has been disabled", sending a user with
        # a never-validated key looking for a setting that does not exist.
        key = _key(team, "openai", state=state)
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", str(key.id)).resolve(team.id)

        assert expected_phrase in exc_info.value.message
        assert "disabled" not in exc_info.value.message

    @pytest.mark.parametrize("active_key_provider", [None, "openai", "anthropic"])
    def test_keyless_requires_provider_key_whatever_the_active_key(self, team, active_key_provider):
        # A judge runs only on its pinned key; the project's active key is no longer a fallback.
        if active_key_provider:
            EvaluationConfig.objects.create(team=team, active_provider_key=_key(team, active_key_provider))

        for spec in (ExplicitModelSpec("openai", "gpt-5-mini", None), UnconfiguredModelSpec()):
            with pytest.raises(ApplicationError) as exc_info:
                spec.resolve(team.id)
            assert _error_type(exc_info) == "provider_key_required"
