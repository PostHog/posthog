import uuid

import pytest

from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team
from posthog.temporal.ai_observability.model_resolution import DefaultModelSpec, ExplicitModelSpec, model_spec

from products.ai_observability.backend.llm import DEFAULT_MODEL_BY_PROVIDER
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


class TestModelSpecFactory:
    def test_null_config_returns_default_spec(self):
        assert isinstance(model_spec(None), DefaultModelSpec)

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

    def test_byok_missing_key_raises_key_not_found(self, team):
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", str(uuid.uuid4())).resolve(team.id)
        assert _error_type(exc_info) == "key_not_found"

    def test_byok_disabled_key_raises_key_invalid(self, team):
        key = _key(team, "openai", state=LLMProviderKey.State.INVALID)
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", str(key.id)).resolve(team.id)
        assert _error_type(exc_info) == "key_invalid"

    def test_trial_allowlisted_model_resolves_without_key(self, team):
        resolved = ExplicitModelSpec("openai", "gpt-5-mini", None).resolve(team.id)
        assert resolved.provider_key is None
        assert not resolved.is_byok

    def test_trial_non_allowlisted_model_raises_model_not_allowed(self, team):
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5", None).resolve(team.id)
        assert _error_type(exc_info) == "model_not_allowed"

    def test_trial_quota_exhausted_raises_trial_limit_reached(self, team):
        EvaluationConfig.objects.create(team=team, trial_eval_limit=100, trial_evals_used=100)
        with pytest.raises(ApplicationError) as exc_info:
            ExplicitModelSpec("openai", "gpt-5-mini", None).resolve(team.id)
        assert _error_type(exc_info) == "trial_limit_reached"


@pytest.mark.django_db
class TestDefaultModelSpec:
    def test_no_active_key_falls_back_to_posthog_trial(self, team):
        resolved = DefaultModelSpec().resolve(team.id)
        assert resolved.provider == "openai"
        assert resolved.model == DEFAULT_MODEL_BY_PROVIDER["openai"]
        assert resolved.provider_key is None
        assert not resolved.is_byok

    def test_no_active_key_with_exhausted_quota_raises_trial_limit_reached(self, team):
        EvaluationConfig.objects.create(team=team, trial_eval_limit=100, trial_evals_used=100)
        with pytest.raises(ApplicationError) as exc_info:
            DefaultModelSpec().resolve(team.id)
        assert _error_type(exc_info) == "trial_limit_reached"

    def test_anthropic_active_key_resolves_to_anthropic_default(self, team):
        # Regression: a null config with an Anthropic active key used to resolve to openai/gpt-5-mini
        # and raise ProviderMismatchError on every generation. It must now follow the key's provider.
        key = _key(team, "anthropic")
        EvaluationConfig.objects.create(team=team, active_provider_key=key)

        resolved = DefaultModelSpec().resolve(team.id)

        assert resolved.provider == "anthropic"
        assert resolved.model == DEFAULT_MODEL_BY_PROVIDER["anthropic"]
        assert resolved.provider_key == key
        assert resolved.is_byok

    def test_gemini_active_key_resolves_to_gemini_default(self, team):
        key = _key(team, "gemini")
        EvaluationConfig.objects.create(team=team, active_provider_key=key)

        resolved = DefaultModelSpec().resolve(team.id)

        assert resolved.provider == "gemini"
        assert resolved.model == DEFAULT_MODEL_BY_PROVIDER["gemini"]
        assert resolved.provider_key == key

    def test_active_key_for_provider_without_default_raises_no_default_model(self, team):
        key = _key(team, "openrouter")
        EvaluationConfig.objects.create(team=team, active_provider_key=key)

        with pytest.raises(ApplicationError) as exc_info:
            DefaultModelSpec().resolve(team.id)
        assert _error_type(exc_info) == "no_default_model"

    def test_disabled_active_key_raises_key_invalid(self, team):
        key = _key(team, "anthropic", state=LLMProviderKey.State.INVALID)
        EvaluationConfig.objects.create(team=team, active_provider_key=key)

        with pytest.raises(ApplicationError) as exc_info:
            DefaultModelSpec().resolve(team.id)
        assert _error_type(exc_info) == "key_invalid"
