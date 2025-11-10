from typing import Any, Literal

from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.models import Experiment, FeatureFlag
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool


class CreateExperimentArgs(BaseModel):
    name: str = Field(description="Experiment name - should clearly describe what is being tested")
    feature_flag_key: str = Field(
        description="Feature flag key (letters, numbers, hyphens, underscores only). Will create a new flag if it doesn't exist."
    )
    description: str | None = Field(
        default=None,
        description="Detailed description of the experiment hypothesis, what changes are being tested, and expected outcomes",
    )
    type: Literal["product", "web"] = Field(
        default="product",
        description="Experiment type: 'product' for backend/API changes, 'web' for frontend UI changes",
    )


class CreateExperimentTool(MaxTool):
    name: Literal["create_experiment"] = "create_experiment"
    description: str = """
Create a new A/B test experiment in the current project.

Experiments allow you to test changes with a controlled rollout and measure their impact.

Use this tool when the user wants to:
- Create a new A/B test experiment
- Set up a controlled experiment to test changes
- Test variants of a feature with users

Examples:
- "Create an experiment to test the new checkout flow"
- "Set up an A/B test for our pricing page redesign"
- "Create an experiment called 'homepage-cta-test' to test different call-to-action buttons

**IMPORTANT**: You must first find or create a multivariate feature flag using `create_feature_flag`, with at least two variants (control and test)."
    """.strip()
    context_prompt_template: str = "Creates a new A/B test experiment in the project"
    args_schema: type[BaseModel] = CreateExperimentArgs

    async def _arun_impl(
        self,
        name: str,
        feature_flag_key: str,
        description: str | None = None,
        type: Literal["product", "web"] = "product",
    ) -> tuple[str, dict[str, Any] | None]:
        # Validate inputs
        if not name or not name.strip():
            return "Experiment name cannot be empty", {"error": "invalid_name"}

        if not feature_flag_key or not feature_flag_key.strip():
            return "Feature flag key cannot be empty", {"error": "invalid_flag_key"}

        @database_sync_to_async
        def create_experiment() -> Experiment:
            # Check if experiment with this name already exists
            existing_experiment = Experiment.objects.filter(team=self._team, name=name, deleted=False).first()
            if existing_experiment:
                raise ValueError(f"An experiment with name '{name}' already exists")

            try:
                feature_flag = FeatureFlag.objects.get(team=self._team, key=feature_flag_key, deleted=False)
            except FeatureFlag.DoesNotExist:
                raise ValueError(f"Feature flag '{feature_flag_key}' does not exist")

            # Validate that the flag has multivariate variants
            multivariate = feature_flag.filters.get("multivariate")
            if not multivariate or not multivariate.get("variants"):
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' must have multivariate variants to be used in an experiment. "
                    f"Create the flag with variants first using the create_feature_flag tool."
                )

            variants = multivariate["variants"]
            if len(variants) < 2:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' must have at least 2 variants for an experiment (e.g., control and test)"
                )

            # If flag already exists and is already used by another experiment, raise error
            existing_experiment_with_flag = Experiment.objects.filter(feature_flag=feature_flag, deleted=False).first()
            if existing_experiment_with_flag:
                raise ValueError(
                    f"Feature flag '{feature_flag_key}' is already used by experiment '{existing_experiment_with_flag.name}'"
                )

            # Use the actual variants from the feature flag
            feature_flag_variants = [
                {
                    "key": variant["key"],
                    "name": variant.get("name", variant["key"]),
                    "rollout_percentage": variant["rollout_percentage"],
                }
                for variant in variants
            ]

            # Create the experiment as a draft (no start_date)
            experiment = Experiment.objects.create(
                team=self._team,
                created_by=self._user,
                name=name,
                description=description or "",
                type=type,
                feature_flag=feature_flag,
                filters={},  # Empty filters for draft
                parameters={
                    "feature_flag_variants": feature_flag_variants,
                    "minimum_detectable_effect": 30,
                },
                metrics=[],
                metrics_secondary=[],
            )

            return experiment

        try:
            experiment = await create_experiment()
            experiment_url = f"/project/{self._team.project_id}/experiments/{experiment.id}"

            return (
                f"Successfully created experiment '{name}'. "
                f"The experiment is in draft mode - you can configure metrics and launch it at {experiment_url}",
                {
                    "experiment_id": experiment.id,
                    "experiment_name": experiment.name,
                    "feature_flag_key": feature_flag_key,
                    "type": type,
                    "url": experiment_url,
                },
            )
        except ValueError as e:
            return f"Failed to create experiment: {str(e)}", {"error": str(e)}
        except Exception as e:
            capture_exception(e)
            return f"Failed to create experiment: {str(e)}", {"error": "creation_failed"}
