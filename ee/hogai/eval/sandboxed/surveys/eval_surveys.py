"""Survey creation eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_surveys.py``. The CI version calls
Max's ``CreateSurveyTool`` directly and checks Django state. This version
asks the sandboxed agent to create surveys through the PostHog MCP
``survey-create`` tool and scores the payload/result it produced.

To run:
    pytest ee/hogai/eval/sandboxed/surveys/eval_surveys.py
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.product_analytics.scorers import INSIGHT_WRITE_TOOLS
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, NoToolCall
from ee.hogai.eval.sandboxed.seeders.survey import seed_survey_feature_flags
from ee.hogai.eval.sandboxed.surveys.scorers import (
    SURVEY_FORBIDDEN_WRITE_TOOLS,
    SurveyCreateOutcome,
    SurveyCreateReturnedId,
    SurveyCreateSchemaAlignment,
    SurveyIdInFinalMessage,
)


def _survey_case(
    *,
    name: str,
    prompt: str,
    expected_survey: dict[str, Any],
    setup: Callable[[CustomPromptSandboxContext], dict[str, Any]] | None = None,
) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=name,
        prompt=prompt,
        expected={
            "survey_created": {"should_create": True},
            "survey_create_alignment": expected_survey,
            "survey_id_in_final_message": {"required": True},
        },
        setup=setup,
    )


@pytest.mark.django_db
async def eval_surveys(
    sandboxed_demo_data: Any,
    pytestconfig: pytest.Config,
    posthog_client: Any,
    mcp_mode: str,
) -> None:
    cases: list[SandboxedEvalCase] = [
        _survey_case(
            name="survey_nps_draft",
            prompt=(
                "Create a draft popover survey named '[sandboxed] NPS Survey' with description "
                "'Net Promoter Score survey'. Add one NPS rating question: "
                "'How likely are you to recommend us to a friend or colleague?' with lower label "
                "'Not likely at all' and upper label 'Extremely likely'. Do not launch it. "
                "Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] NPS Survey",
                "description": "Net Promoter Score survey",
                "type": "popover",
                "should_launch": False,
                "questions": [
                    {
                        "type": "rating",
                        "question": "How likely are you to recommend us to a friend or colleague?",
                        "scale": 10,
                        "display": "number",
                        "lowerBoundLabel": "Not likely at all",
                        "upperBoundLabel": "Extremely likely",
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_csat_launched",
            prompt=(
                "Create and launch a popover survey named '[sandboxed] CSAT Survey' with description "
                "'Customer satisfaction survey'. It should ask one CSAT rating question: "
                "'How satisfied are you with our product?' Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] CSAT Survey",
                "description": "Customer satisfaction survey",
                "type": "popover",
                "should_launch": True,
                "questions": [
                    {
                        "type": "rating",
                        "question": "How satisfied are you with our product?",
                        "scale": 5,
                        "display": "number",
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_nps_with_followup",
            prompt=(
                "Create a draft popover survey named '[sandboxed] NPS with Follow-up' with description "
                "'NPS survey with optional follow-up question'. Add two questions in this order: an NPS rating "
                "question 'How likely are you to recommend us?' and an optional open-text follow-up "
                "'What could we improve?'. Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] NPS with Follow-up",
                "description": "NPS survey with optional follow-up question",
                "type": "popover",
                "should_launch": False,
                "questions": [
                    {
                        "type": "rating",
                        "question": "How likely are you to recommend us?",
                        "scale": 10,
                        "display": "number",
                    },
                    {
                        "type": "open",
                        "question": "What could we improve?",
                        "optional": True,
                    },
                ],
            },
        ),
        _survey_case(
            name="survey_pmf_single_choice",
            prompt=(
                "Create a draft popover PMF survey named '[sandboxed] PMF Survey' with description "
                "'Product-market fit survey'. Ask one single-choice question: "
                "'How would you feel if you could no longer use our product?' with choices "
                "'Very disappointed', 'Somewhat disappointed', and 'Not disappointed'. "
                "Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] PMF Survey",
                "description": "Product-market fit survey",
                "type": "popover",
                "should_launch": False,
                "questions": [
                    {
                        "type": "single_choice",
                        "question": "How would you feel if you could no longer use our product?",
                        "choices": ["Very disappointed", "Somewhat disappointed", "Not disappointed"],
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_checkout_feature_flag",
            prompt=(
                "Create a draft popover survey named '[sandboxed] Checkout Feedback' with description "
                "'Feedback for new checkout flow users'. Ask one open-text question: "
                "'How was your checkout experience?' Link it to the existing feature flag with key "
                "'new-checkout-flow'. Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] Checkout Feedback",
                "description": "Feedback for new checkout flow users",
                "type": "popover",
                "should_launch": False,
                "linked_flag_key": "new-checkout-flow",
                "questions": [
                    {
                        "type": "open",
                        "question": "How was your checkout experience?",
                    }
                ],
            },
            setup=seed_survey_feature_flags,
        ),
        _survey_case(
            name="survey_ab_test_treatment_variant",
            prompt=(
                "Create a draft popover survey named '[sandboxed] A/B Test Treatment Survey' with description "
                "'Survey for users in treatment variant'. Ask one CSAT rating question: "
                "'How do you like the new design?' Link it to the existing feature flag with key "
                "'ab-test-experiment' and target only users in the 'treatment' variant. "
                "Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] A/B Test Treatment Survey",
                "description": "Survey for users in treatment variant",
                "type": "popover",
                "should_launch": False,
                "linked_flag_key": "ab-test-experiment",
                "conditions": {"linkedFlagVariant": "treatment"},
                "questions": [
                    {
                        "type": "rating",
                        "question": "How do you like the new design?",
                        "scale": 5,
                        "display": "number",
                    }
                ],
            },
            setup=seed_survey_feature_flags,
        ),
        _survey_case(
            name="survey_pricing_page_url_targeting",
            prompt=(
                "Create a draft popover survey named '[sandboxed] Pricing Page Feedback' with description "
                "'Feedback from pricing page visitors'. Ask one single-choice question: "
                "'Is our pricing clear?' with choices 'Yes, very clear', 'Somewhat clear', and "
                "'Not clear at all'. Target URLs containing '/pricing'. Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] Pricing Page Feedback",
                "description": "Feedback from pricing page visitors",
                "type": "popover",
                "should_launch": False,
                "conditions": {"url": "/pricing", "urlMatchType": "icontains"},
                "questions": [
                    {
                        "type": "single_choice",
                        "question": "Is our pricing clear?",
                        "choices": ["Yes, very clear", "Somewhat clear", "Not clear at all"],
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_feature_usage_multiple_choice",
            prompt=(
                "Create a draft popover survey named '[sandboxed] Feature Usage Survey' with description "
                "'Survey about feature usage'. Ask one multiple-choice question: 'Which features do you use most?' "
                "with choices 'Dashboard', 'Insights', 'Session Replay', 'Feature Flags', and 'Experiments'. "
                "Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] Feature Usage Survey",
                "description": "Survey about feature usage",
                "type": "popover",
                "should_launch": False,
                "questions": [
                    {
                        "type": "multiple_choice",
                        "question": "Which features do you use most?",
                        "choices": ["Dashboard", "Insights", "Session Replay", "Feature Flags", "Experiments"],
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_widget_feedback",
            prompt=(
                "Create a draft widget survey named '[sandboxed] Widget Feedback' with description "
                "'Widget-based feedback survey'. Ask one open-text question: "
                "'What do you think of our product?' Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] Widget Feedback",
                "description": "Widget-based feedback survey",
                "type": "widget",
                "should_launch": False,
                "questions": [
                    {
                        "type": "open",
                        "question": "What do you think of our product?",
                    }
                ],
            },
        ),
        _survey_case(
            name="survey_empty_questions_allowed",
            prompt=(
                "Create a draft popover survey named '[sandboxed] Empty Questions Survey' with description "
                "'Survey with no questions'. Use an empty questions list and do not add a placeholder question. "
                "Return the created survey ID in your final answer."
            ),
            expected_survey={
                "name": "[sandboxed] Empty Questions Survey",
                "description": "Survey with no questions",
                "type": "popover",
                "should_launch": False,
                "questions": [],
            },
        ),
    ]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-surveys-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCall(
                forbidden=SURVEY_FORBIDDEN_WRITE_TOOLS | INSIGHT_WRITE_TOOLS,
                name="no_forbidden_survey_side_effects",
            ),
            SurveyCreateOutcome(),
            SurveyCreateReturnedId(),
            SurveyCreateSchemaAlignment(),
            SurveyIdInFinalMessage(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
