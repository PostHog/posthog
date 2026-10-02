from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from django.utils import timezone

from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition

if TYPE_CHECKING:
    from products.ai_observability.backend.models.score_definitions import ScoreDefinitionVersion
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

BASELINE_NAME = "[lookup] Offline baseline"
CANDIDATE_NAME = "[lookup] Offline candidate"
CHANGED_RULE_NAME = "[lookup] Offline changed rule"


def seed_offline_comparison(context: CustomPromptSandboxContext) -> dict[str, str]:
    definition = ScoreDefinition.objects.create(team_id=context.team_id, name="Arithmetic correctness", kind="boolean")
    original_version = definition.create_new_version(config={"true_is_failure": False}, created_by=None)
    changed_version = definition.create_new_version(config={"true_is_failure": True}, created_by=None)
    now = timezone.now()
    ids: dict[str, str] = {"scorer_id": str(definition.id)}
    runs: list[tuple[str, ScoreDefinitionVersion, list[bool | str | None]]] = [
        (BASELINE_NAME, original_version, [True, False, True, "error"]),
        (CANDIDATE_NAME, original_version, [True, True, None, "error"]),
        (CHANGED_RULE_NAME, changed_version, [True, False, True, "error"]),
    ]
    for index, (name, version, values) in enumerate(runs):
        experiment = OfflineExperiment.objects.for_team(context.team_id).create(
            id=uuid4(),
            team_id=context.team_id,
            name=name,
            started_at=now - timedelta(hours=3 - index),
            created_at=now - timedelta(minutes=10),
            finished_at=now,
            status="completed",
            suite_key="arithmetic",
            dataset_source="external",
            dataset_identifier="arithmetic-cases",
            dataset_revision_identifier="revision-1",
            application_version="baseline" if name != CANDIDATE_NAME else "candidate",
            submission_fingerprint="a" * 64,
        )
        ids[name] = str(experiment.id)
        for case_index, value in enumerate(values, start=1):
            item = OfflineExperimentItem.objects.for_team(context.team_id).create(
                id=uuid4(),
                team_id=context.team_id,
                experiment=experiment,
                case_key=f"case-{case_index}",
                dataset_item_identifier=f"arithmetic-{case_index}",
                accepted_at=now - timedelta(minutes=5),
                payload_state="available",
                payload_expires_at=now + timedelta(days=30),
                submission_fingerprint="b" * 64,
            )
            OfflineExperimentItemPayload.objects.for_team(context.team_id).create(
                team_id=context.team_id,
                item=item,
                data={"input": "What is 2 + 2?", "output": "5" if value is False else "4", "expected_output": "4"},
            )
            if value is None:
                continue
            result = OfflineEvaluationResult.objects.for_team(context.team_id).create(
                team_id=context.team_id,
                item=item,
                scorer_definition=definition,
                scorer_version=version,
                status="error" if value == "error" else "ok",
                boolean_value=value if isinstance(value, bool) else None,
                error_code="timeout" if value == "error" else None,
                accepted_at=now - timedelta(minutes=5),
                payload_state="available",
                payload_expires_at=now + timedelta(days=30),
                submission_fingerprint="c" * 64,
            )
            OfflineEvaluationResultPayload.objects.for_team(context.team_id).create(
                team_id=context.team_id,
                result=result,
                data={
                    "reasoning": "The answer is 5 but the expected arithmetic result is 4."
                    if value is False
                    else "Evaluation evidence."
                },
            )
    return ids
