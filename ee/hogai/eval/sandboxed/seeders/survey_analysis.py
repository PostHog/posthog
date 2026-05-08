"""Seed survey-response fixtures for sandboxed survey-analysis evals."""

from __future__ import annotations

import uuid
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from posthog.models.event.util import bulk_create_events
from posthog.models.team import Team

from products.event_definitions.backend.models import EventDefinition, PropertyDefinition, PropertyType
from products.surveys.backend.models import Survey
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

logger = logging.getLogger(__name__)

SURVEY_ANALYSIS_SEED_NAMESPACE = uuid.UUID("9df7694a-e7eb-40cc-8897-1f80e852c4d7")


class SurveyAnalysisQuestionSeed(TypedDict):
    question: str
    responses: tuple[str, ...]


class SurveyAnalysisSeed(TypedDict):
    key: str
    survey_name: str
    questions: list[SurveyAnalysisQuestionSeed]


def build_survey_analysis_setup(seed: SurveyAnalysisSeed) -> Callable[[CustomPromptSandboxContext], dict[str, Any]]:
    def _setup(context: CustomPromptSandboxContext) -> dict[str, Any]:
        return seed_survey_analysis_case(context, seed)

    _setup.__name__ = f"seed_survey_analysis_{seed['key']}"
    return _setup


def seed_survey_analysis_case(context: CustomPromptSandboxContext, seed: SurveyAnalysisSeed) -> dict[str, Any]:
    team = Team.objects.get(id=context.team_id)
    now = datetime.now(UTC)
    questions = [
        {
            "id": _question_id(seed["key"], index),
            "type": "open",
            "question": question["question"],
            "optional": False,
        }
        for index, question in enumerate(seed["questions"])
    ]

    survey = Survey.objects.create(
        team=team,
        created_by_id=context.user_id,
        name=seed["survey_name"],
        description=f"Sandboxed survey-analysis fixture for {seed['key']}",
        questions=questions,
        type=Survey.SurveyType.POPOVER,
        start_date=now - timedelta(days=7),
    )

    _seed_taxonomy(team)
    _seed_survey_response_events(team, survey, seed, now)

    response_count = _response_count(seed)
    payload = {
        "survey_analysis": {
            "survey_id": str(survey.id),
            "survey_name": survey.name,
            "response_count": response_count,
            "questions": [
                {
                    "id": questions[index]["id"],
                    "question": question["question"],
                    "responses": list(question["responses"]),
                }
                for index, question in enumerate(seed["questions"])
            ],
        }
    }
    logger.info(
        "Seeded survey-analysis fixture for team_id=%s survey_id=%s responses=%d",
        team.id,
        survey.id,
        response_count,
    )
    return payload


def _response_count(seed: SurveyAnalysisSeed) -> int:
    return sum(len(question["responses"]) for question in seed["questions"])


def _question_id(case_key: str, index: int) -> str:
    return str(uuid.uuid5(SURVEY_ANALYSIS_SEED_NAMESPACE, f"{case_key}:question:{index}"))


def _seed_taxonomy(team: Team) -> None:
    EventDefinition.objects.get_or_create(team=team, project=team.project, name="survey sent")
    for property_name in (
        "$survey_id",
        "$survey_submission_id",
        "$survey_questions",
        "$survey_response",
        "$survey_response_1",
    ):
        PropertyDefinition.objects.get_or_create(
            team=team,
            project=team.project,
            name=property_name,
            type=PropertyDefinition.Type.EVENT,
            defaults={"property_type": PropertyType.String},
        )


def _seed_survey_response_events(
    team: Team,
    survey: Survey,
    seed: SurveyAnalysisSeed,
    now: datetime,
) -> None:
    events: list[dict[str, Any]] = []
    sequence = 0
    survey_questions = survey.questions or []
    for question_index, question in enumerate(seed["questions"]):
        question_id = _question_id(seed["key"], question_index)
        index_key = "$survey_response" if question_index == 0 else f"$survey_response_{question_index}"
        id_key = f"$survey_response_{question_id}"
        for response in question["responses"]:
            sequence += 1
            response_time = now - timedelta(hours=4, minutes=sequence)
            events.append(
                {
                    "event": "survey sent",
                    "team": team,
                    "distinct_id": f"survey-analysis-{seed['key']}-{sequence}",
                    "timestamp": response_time,
                    "properties": {
                        "$survey_id": str(survey.id),
                        "$survey_submission_id": str(
                            uuid.uuid5(SURVEY_ANALYSIS_SEED_NAMESPACE, f"{survey.id}:{sequence}")
                        ),
                        "$survey_questions": survey_questions,
                        index_key: response,
                        id_key: response,
                    },
                }
            )

    bulk_create_events(events)
