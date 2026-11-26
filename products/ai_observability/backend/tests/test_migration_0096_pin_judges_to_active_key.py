from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class TestPinJudgesToActiveKey(NonAtomicTestMigrations):
    app = "ai_observability"
    migrate_from = "0095_experiment_score_history_index"
    migrate_to = "0096_pin_judges_to_active_key"

    def setUpBeforeMigration(self, apps: Any) -> None:
        LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
        LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")
        Evaluation = apps.get_model("ai_observability", "Evaluation")
        EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")

        def key(provider: str) -> Any:
            return LLMProviderKey.objects.create(
                team_id=self.team.id, provider=provider, name=provider, state="ok", encrypted_config={}
            )

        self.active_key, other_key = key("openai"), key("openai")
        EvaluationConfig.objects.create(team_id=self.team.id, active_provider_key=self.active_key)

        def judge(name: str, evaluation_type: str = "llm_judge", deleted: bool = False, **config: Any) -> str:
            model_configuration = (
                LLMModelConfiguration.objects.create(team_id=self.team.id, **config) if config else None
            )
            return str(
                Evaluation.objects.create(
                    team_id=self.team.id,
                    name=name,
                    evaluation_type=evaluation_type,
                    evaluation_config={},
                    output_type="boolean",
                    model_configuration=model_configuration,
                    deleted=deleted,
                ).id
            )

        self.judges = {
            "no_config": judge("no_config"),
            "same_provider_no_key": judge("same_provider_no_key", provider="openai", model="gpt-5-mini"),
            "other_provider_no_key": judge("other_provider_no_key", provider="anthropic", model="claude-haiku-4-5"),
            "pinned_elsewhere": judge(
                "pinned_elsewhere", provider="openai", model="gpt-5-mini", provider_key=other_key
            ),
            "deleted": judge("deleted", deleted=True),
            "code": judge("code", evaluation_type="hog"),
        }
        self.other_key = other_key

    def test_pins_only_judges_that_run_on_the_active_key(self) -> None:
        Evaluation = self.apps.get_model("ai_observability", "Evaluation")  # type: ignore[union-attr]
        pinned = {
            name: Evaluation.objects.filter(id=evaluation_id)
            .values_list(
                "model_configuration__provider", "model_configuration__model", "model_configuration__provider_key_id"
            )
            .get()
            for name, evaluation_id in self.judges.items()
        }

        assert pinned == {
            "no_config": ("openai", "gpt-6-luna", self.active_key.id),
            "same_provider_no_key": ("openai", "gpt-5-mini", self.active_key.id),
            "other_provider_no_key": ("anthropic", "claude-haiku-4-5", None),
            "pinned_elsewhere": ("openai", "gpt-5-mini", self.other_key.id),
            "deleted": (None, None, None),
            "code": (None, None, None),
        }
