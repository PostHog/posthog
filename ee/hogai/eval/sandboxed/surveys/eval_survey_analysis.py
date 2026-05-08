"""Survey-analysis eval cases for the sandboxed coding agent.

Intent mirrors ``ee/hogai/eval/ci/eval_survey_analysis.py``. The CI eval
calls Max's ``SurveyAnalysisTool`` directly and grades whether the tool
formats response text well enough for the agent to analyze. This sandboxed
version seeds real survey response events, asks the agent to analyze them
through PostHog MCP, and grades the ``execute-sql`` response retrieval plus
the final analysis.

To run:
    pytest ee/hogai/eval/sandboxed/surveys/eval_survey_analysis.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ee.hogai.eval.sandboxed.base import SandboxedPublicEval
from ee.hogai.eval.sandboxed.config import SandboxedEvalCase
from ee.hogai.eval.sandboxed.retrieval.scorers import SkillLoaded
from ee.hogai.eval.sandboxed.scorers import ExitCodeZero, LastToolCallNot
from ee.hogai.eval.sandboxed.seeders.survey_analysis import SurveyAnalysisSeed, build_survey_analysis_setup
from ee.hogai.eval.sandboxed.surveys.scorers import (
    SURVEY_FORBIDDEN_WRITE_TOOLS,
    SURVEY_RESPONSE_TOOL_NAME,
    NoToolCallOrError,
    RequiredToolCallOrError,
    SurveyAnalysisAnswerAlignment,
    SurveyIdUsed,
    SurveyResponseRetrieval,
)


@dataclass(frozen=True)
class SurveyAnalysisQuestion:
    question: str
    responses: tuple[str, ...]


@dataclass(frozen=True)
class SurveyAnalysisScenario:
    key: str
    survey_name: str
    questions: tuple[SurveyAnalysisQuestion, ...]
    sentiment: str
    themes: tuple[str, ...]
    recommendations: tuple[str, ...]

    @property
    def response_count(self) -> int:
        return sum(len(question.responses) for question in self.questions)

    def expected(self) -> dict[str, Any]:
        return {
            "survey_name": self.survey_name,
            "response_count": self.response_count,
            "question_count": len(self.questions),
            "sentiment": self.sentiment,
            "themes": list(self.themes),
            "recommendations": list(self.recommendations),
            "questions": [question.question for question in self.questions],
        }

    def seed_payload(self) -> SurveyAnalysisSeed:
        return {
            "key": self.key,
            "survey_name": self.survey_name,
            "questions": [
                {"question": question.question, "responses": question.responses} for question in self.questions
            ],
        }


SURVEY_ANALYSIS_SCENARIOS: tuple[SurveyAnalysisScenario, ...] = (
    SurveyAnalysisScenario(
        key="placeholder_data",
        survey_name="[lookup] Placeholder survey responses",
        questions=(
            SurveyAnalysisQuestion(
                question="What do you think about our product?",
                responses=("fasdfasdf", "testing"),
            ),
        ),
        sentiment="neutral / unusable",
        themes=("placeholder or test data", "insufficient real feedback"),
        recommendations=("collect genuine responses before drawing product conclusions",),
    ),
    SurveyAnalysisScenario(
        key="mixed_feedback",
        survey_name="[lookup] Mixed improvement feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="How can we improve our product?",
                responses=(
                    "The main dashboard is cluttered and hard to navigate quickly",
                    "Interface could be more intuitive, buttons are not where I expect",
                    "Navigation menu needs work - took me 5 minutes to find settings",
                    "Love the clean design but some UI elements are too small on mobile",
                    "Search functionality in the interface is hard to find and use",
                    "The sidebar gets in the way on smaller screens",
                    "Loading times are really slow, especially for large datasets",
                    "App crashes when I upload files bigger than 50MB",
                    "Performance on mobile is terrible, very laggy scrolling",
                    "Would love faster sync between devices, currently takes forever",
                ),
            ),
        ),
        sentiment="mixed to negative",
        themes=("navigation and interface clarity", "mobile usability", "performance and stability"),
        recommendations=("simplify navigation", "improve mobile layout", "investigate slow loads and crashes"),
    ),
    SurveyAnalysisScenario(
        key="positive_feedback",
        survey_name="[lookup] Customer satisfaction feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="What do you like most about our product?",
                responses=(
                    "The user interface is incredibly clean and intuitive to navigate",
                    "Love the modern design - feels professional and polished",
                    "Dashboard layout makes it easy to find everything I need quickly",
                    "The visual hierarchy is perfect - important things stand out",
                    "Responsive design works beautifully on all my devices",
                    "Color scheme and typography are excellent choices",
                    "Interface feels modern and doesn't look outdated like competitors",
                    "Lightning fast loading times even with large datasets",
                    "Never experienced crashes or bugs - very stable platform",
                    "Real-time updates happen instantly without any lag",
                    "Performance is consistently excellent across all features",
                    "Handles our heavy usage without any slowdowns",
                    "Customer support team is incredibly knowledgeable and responsive",
                    "Got help within 15 minutes via chat - amazing service",
                    "Support goes above and beyond to solve problems",
                    "Documentation is thorough and support articles are really helpful",
                    "Seamless integration with all our existing tools and workflows",
                    "API is well-documented and easy to implement",
                    "Fits perfectly into our daily workflow without disruption",
                    "Export functionality works exactly as expected with our systems",
                ),
            ),
        ),
        sentiment="positive",
        themes=("clean UI and visual design", "speed and reliability", "responsive support", "integrations and API"),
        recommendations=(
            "protect current UX strengths",
            "keep performance high",
            "promote support and integration wins",
        ),
    ),
    SurveyAnalysisScenario(
        key="negative_feedback",
        survey_name="[lookup] Product issues feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="What issues or problems have you encountered with our product?",
                responses=(
                    "App crashes constantly when I try to upload files larger than 100MB",
                    "Loading times are painfully slow - sometimes 30+ seconds for simple queries",
                    "System goes down for maintenance way too often, always during business hours",
                    "Data syncing is unreliable - lost work multiple times due to sync failures",
                    "Memory usage is insane - laptop becomes unusable when running your app",
                    "Frequent timeouts when working with larger datasets, very frustrating",
                    "Support tickets take 3-5 days to get any response, completely unacceptable",
                    "When support finally responds, they ask basic questions I already answered",
                    "No phone support option - only slow email tickets for urgent issues",
                    "Support team clearly doesn't understand their own product features",
                    "Way overpriced compared to competitors offering similar features",
                    "Hidden fees keep appearing - billing is not transparent at all",
                    "Free tier is basically useless - forces you to upgrade immediately",
                    "Poor value for money - paying premium prices for basic functionality",
                    "No bulk operations - have to do everything one by one, super tedious",
                    "Missing basic export options that every competitor has",
                    "No offline mode - completely useless when internet is spotty",
                    "Collaboration features are primitive compared to modern standards",
                ),
            ),
        ),
        sentiment="negative",
        themes=("performance and reliability failures", "slow support", "pricing concerns", "missing features"),
        recommendations=("prioritize stability fixes", "improve support response times", "review pricing transparency"),
    ),
    SurveyAnalysisScenario(
        key="multi_question",
        survey_name="[lookup] Comprehensive product feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="What do you like about our product?",
                responses=(
                    "Incredibly intuitive interface - figured it out in minutes",
                    "Simple workflow that doesn't require extensive training",
                    "Clean design makes complex tasks feel manageable",
                    "Onboarding process was smooth and well-guided",
                    "Everything is where you'd expect it to be",
                    "No steep learning curve unlike other similar tools",
                    "User experience feels thoughtfully designed",
                    "Great balance of powerful features without complexity",
                    "Rock solid performance - never had any crashes or issues",
                    "Data integrity is excellent, never lost any work",
                    "Consistent uptime - can always rely on it being available",
                    "Fast loading and response times across all features",
                    "Auto-save functionality has saved me multiple times",
                    "Handles large amounts of data without slowing down",
                ),
            ),
            SurveyAnalysisQuestion(
                question="What could we improve or add?",
                responses=(
                    "Need bulk operations for managing hundreds of items at once",
                    "Advanced filtering and search capabilities would be game-changing",
                    "API access for custom integrations with our internal tools",
                    "Custom dashboards and reporting features for management",
                    "Automation rules and workflows to reduce manual work",
                    "More granular permission controls for team management",
                    "Advanced analytics and insights into usage patterns",
                    "Better collaboration tools for larger teams",
                    "White-label options for client-facing implementations",
                    "Mobile app needs significant performance improvements",
                    "Offline mode for working without internet connection",
                    "Native mobile apps instead of web-based mobile experience",
                    "Better mobile interface optimization for small screens",
                    "Faster loading times on mobile devices",
                    "Push notifications for mobile app would be useful",
                    "Dark mode theme option for better user experience",
                    "Keyboard shortcuts for power users on desktop",
                    "Better browser compatibility, especially for older versions",
                ),
            ),
        ),
        sentiment="mixed",
        themes=("ease of use and reliability", "advanced workflow features", "mobile improvements", "collaboration"),
        recommendations=("preserve simple UX", "prioritize bulk operations and filtering", "improve mobile experience"),
    ),
    SurveyAnalysisScenario(
        key="service_feedback",
        survey_name="[lookup] Support service feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="How would you rate our customer service experience?",
                responses=(
                    "Customer support resolved my issue within 2 hours - absolutely fantastic",
                    "Representative was knowledgeable and patient, walked me through everything step by step",
                    "24/7 chat support is a game changer for our international team",
                    "Proactive communication about updates and maintenance - really appreciate that",
                    "Technical support team understood our complex setup immediately",
                    "Follow-up email to ensure problem was fully resolved shows they care",
                    "Support documentation is comprehensive and easy to follow",
                    "Video tutorials provided by support team were extremely helpful",
                    "Good service overall but had to wait 30 minutes for initial response",
                    "Support was helpful but had to explain the issue multiple times",
                    "Eventually got the answer I needed, took a few back-and-forth messages",
                    "Phone support was good but email responses are quite slow",
                    "Representative was polite but didn't seem familiar with advanced features",
                    "Got my problem solved but the process felt longer than necessary",
                    "Waited over 2 hours for someone to respond to urgent issue",
                    "First agent couldn't help, was transferred 3 times before getting answer",
                    "Support ticket was closed without resolution, had to reopen",
                    "Generic responses that didn't address my specific technical problem",
                ),
            ),
        ),
        sentiment="mixed leaning positive",
        themes=("knowledgeable and caring support", "response-time inconsistency", "handoff and expertise gaps"),
        recommendations=("standardize first response speed", "reduce transfers", "improve advanced-feature training"),
    ),
    SurveyAnalysisScenario(
        key="feature_requests",
        survey_name="[lookup] Feature request feedback",
        questions=(
            SurveyAnalysisQuestion(
                question="What features would you like to see added or improved?",
                responses=(
                    "Integration with Slack would revolutionize our team communication workflow",
                    "Google Workspace SSO integration is desperately needed for enterprise deployment",
                    "Zapier integration would allow us to automate so many manual processes",
                    "Microsoft Teams integration for seamless file sharing and notifications",
                    "API endpoints for custom reporting would enable our dashboard integrations",
                    "Salesforce CRM integration to sync customer data automatically",
                    "Webhook support for real-time data synchronization with our systems",
                    "Offline mode for mobile app would be incredible for field work",
                    "Push notifications for important updates and deadlines",
                    "Mobile photo upload with automatic compression and organization",
                    "Better tablet interface optimized for larger screens",
                    "Voice-to-text input for quick note taking on mobile",
                    "Dark mode theme for mobile app to reduce eye strain",
                    "Advanced analytics dashboard with customizable KPI tracking",
                    "Automated report scheduling and email delivery to stakeholders",
                    "Data export in more formats like Excel, PDF, and CSV",
                    "Real-time collaboration analytics to track team productivity",
                    "Historical trend analysis with predictive insights",
                    "Keyboard shortcuts for power users would dramatically improve efficiency",
                    "Multi-language support for our international team members",
                    "Bulk operations for managing large datasets more efficiently",
                    "Template system for recurring workflows and standardized processes",
                ),
            ),
        ),
        sentiment="constructive / feature-request focused",
        themes=("third-party integrations", "mobile capability", "analytics and reporting", "workflow efficiency"),
        recommendations=(
            "prioritize integrations",
            "scope mobile offline and notification work",
            "expand reporting exports",
        ),
    ),
)


def _survey_analysis_prompt(scenario: SurveyAnalysisScenario) -> str:
    return (
        f'Analyze the open-ended responses for the survey named "{scenario.survey_name}" in this PostHog project. '
        "Use PostHog MCP tools to find the survey ID, then use that ID to retrieve the actual response text. "
        "In your final answer include the total open-ended response count, key themes with examples, "
        "overall sentiment, actionable insights, and recommendations. Do not create or modify any surveys, "
        "insights, dashboards, or other saved PostHog content."
    )


def _survey_analysis_case(scenario: SurveyAnalysisScenario) -> SandboxedEvalCase:
    return SandboxedEvalCase(
        name=f"survey_analysis_{scenario.key}",
        prompt=_survey_analysis_prompt(scenario),
        expected={"survey_analysis": scenario.expected()},
        setup=build_survey_analysis_setup(scenario.seed_payload()),
        metadata={"source_ci_eval": "ee/hogai/eval/ci/eval_survey_analysis.py"},
    )


@pytest.mark.django_db
async def eval_survey_analysis(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    cases = [_survey_analysis_case(scenario) for scenario in SURVEY_ANALYSIS_SCENARIOS]

    await SandboxedPublicEval(
        experiment_name=f"sandboxed-surveys-{mcp_mode}",
        cases=cases,
        scorers=[
            ExitCodeZero(),
            NoToolCallOrError(forbidden=SURVEY_FORBIDDEN_WRITE_TOOLS, name="no_persistent_write_attempt"),
            LastToolCallNot(forbidden=SURVEY_FORBIDDEN_WRITE_TOOLS, name="last_call_not_persistent_write"),
            RequiredToolCallOrError(
                required={SURVEY_RESPONSE_TOOL_NAME},
                name="attempted_execute_sql_for_responses",
            ),
            SkillLoaded("querying-posthog-data", name="querying_posthog_data_skill_loaded"),
            SurveyIdUsed(),
            SurveyResponseRetrieval(),
            SurveyAnalysisAnswerAlignment(),
        ],
        pytestconfig=pytestconfig,
        sandboxed_demo_data=sandboxed_demo_data,
        posthog_client=posthog_client,
    )
