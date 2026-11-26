from typing import Any

from posthog.test.base import NonAtomicTestMigrations

from posthog.models import Team


class TestPinJudgesToActiveKey(NonAtomicTestMigrations):
    app = "ai_observability"
    migrate_from = "0095_experiment_score_history_index"
    migrate_to = "0096_pin_judges_to_active_key"

    def setUpBeforeMigration(self, apps: Any) -> None:
        LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
        LLMModelConfiguration = apps.get_model("ai_observability", "LLMModelConfiguration")
        Evaluation = apps.get_model("ai_observability", "Evaluation")
        EvaluationConfig = apps.get_model("ai_observability", "EvaluationConfig")

        def key(team_id: int, provider: str) -> Any:
            return LLMProviderKey.objects.create(
                team_id=team_id, provider=provider, name=provider, state="ok", encrypted_config={}
            )

        def judge(
            team_id: int, name: str, evaluation_type: str = "llm_judge", deleted: bool = False, **config: Any
        ) -> str:
            model_configuration = LLMModelConfiguration.objects.create(team_id=team_id, **config) if config else None
            return str(
                Evaluation.objects.create(
                    team_id=team_id,
                    name=name,
                    evaluation_type=evaluation_type,
                    evaluation_config={},
                    output_type="boolean",
                    model_configuration=model_configuration,
                    deleted=deleted,
                ).id
            )

        team = self.team.id
        self.active_key, self.other_key = key(team, "openai"), key(team, "openai")
        EvaluationConfig.objects.create(team_id=team, active_provider_key=self.active_key)

        # OpenRouter has no default model, so only a judge that already names an OpenRouter model can be pinned.
        router_team = Team.objects.create(organization=self.organization, name="OpenRouter team").id
        self.router_key = key(router_team, "openrouter")
        EvaluationConfig.objects.create(team_id=router_team, active_provider_key=self.router_key)

        no_config_team = Team.objects.create(organization=self.organization, name="No config team").id

        self.judges = {
            "no_config": judge(team, "no_config"),
            "same_provider_no_key": judge(team, "same_provider_no_key", provider="openai", model="gpt-5-mini"),
            "other_provider_no_key": judge(
                team, "other_provider_no_key", provider="anthropic", model="claude-haiku-4-5"
            ),
            "pinned_elsewhere": judge(
                team, "pinned_elsewhere", provider="openai", model="gpt-5-mini", provider_key=self.other_key
            ),
            "deleted": judge(team, "deleted", deleted=True),
            "code": judge(team, "code", evaluation_type="hog"),
            "router_no_config": judge(router_team, "router_no_config"),
            "router_no_key": judge(router_team, "router_no_key", provider="openrouter", model="openai/gpt-5-mini"),
            "team_without_active_key": judge(
                no_config_team, "team_without_active_key", provider="openai", model="gpt-5-mini"
            ),
        }

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
            "router_no_config": (None, None, None),
            "router_no_key": ("openrouter", "openai/gpt-5-mini", self.router_key.id),
            "team_without_active_key": ("openai", "gpt-5-mini", None),
        }
