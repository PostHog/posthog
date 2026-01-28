import uuid
import datetime

import pytest
from unittest.mock import patch

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.models import Survey

from products.surveys.backend.max_tools import SurveyAnalysisTool

from ee.hogai.utils.types.base import AssistantState

from ..base import MaxPublicEval


# Helper functions to generate test response data
def generate_test_data_responses():
    """Generate clearly placeholder/test responses that should be detected as test data."""
    return [
        {
            "questionName": "What do you think about our product?",
            "questionId": "q1",
            "responses": [
                {
                    "responseText": "fasdfasdf",
                    "isOpenEnded": True,
                },
                {
                    "responseText": "testing",
                    "isOpenEnded": True,
                },
            ],
        }
    ]


def generate_mixed_data_responses():
    """Generate mixed test and genuine responses (60% test, 40% genuine)."""
    test_responses: list[dict] = []

    genuine_responses = [
        # Interface feedback
        {
            "responseText": "The main dashboard is cluttered and hard to navigate quickly",
            "isOpenEnded": True,
        },
        {
            "responseText": "Interface could be more intuitive, buttons are not where I expect",
            "isOpenEnded": True,
        },
        {
            "responseText": "Navigation menu needs work - took me 5 minutes to find settings",
            "isOpenEnded": True,
        },
        {
            "responseText": "Love the clean design but some UI elements are too small on mobile",
            "isOpenEnded": True,
        },
        {
            "responseText": "Search functionality in the interface is hard to find and use",
            "isOpenEnded": True,
        },
        {
            "responseText": "The sidebar gets in the way on smaller screens",
            "isOpenEnded": True,
        },
        # Performance feedback
        {
            "responseText": "Loading times are really slow, especially for large datasets",
            "isOpenEnded": True,
        },
        {
            "responseText": "App crashes when I upload files bigger than 50MB",
            "isOpenEnded": True,
        },
        {
            "responseText": "Performance on mobile is terrible, very laggy scrolling",
            "isOpenEnded": True,
        },
        {
            "responseText": "Would love faster sync between devices, currently takes forever",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "How can we improve our product?",
            "questionId": "q1",
            "responses": test_responses + genuine_responses,
        }
    ]


def generate_positive_feedback_responses():
    """Generate genuine positive feedback across multiple themes."""
    ui_design_responses = [
        {
            "responseText": "The user interface is incredibly clean and intuitive to navigate",
            "isOpenEnded": True,
        },
        {
            "responseText": "Love the modern design - feels professional and polished",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dashboard layout makes it easy to find everything I need quickly",
            "isOpenEnded": True,
        },
        {
            "responseText": "The visual hierarchy is perfect - important things stand out",
            "isOpenEnded": True,
        },
        {
            "responseText": "Responsive design works beautifully on all my devices",
            "isOpenEnded": True,
        },
        {
            "responseText": "Color scheme and typography are excellent choices",
            "isOpenEnded": True,
        },
        {
            "responseText": "Interface feels modern and doesn't look outdated like competitors",
            "isOpenEnded": True,
        },
    ]

    performance_responses = [
        {
            "responseText": "Lightning fast loading times even with large datasets",
            "isOpenEnded": True,
        },
        {
            "responseText": "Never experienced crashes or bugs - very stable platform",
            "isOpenEnded": True,
        },
        {
            "responseText": "Real-time updates happen instantly without any lag",
            "isOpenEnded": True,
        },
        {
            "responseText": "Performance is consistently excellent across all features",
            "isOpenEnded": True,
        },
        {
            "responseText": "Handles our heavy usage without any slowdowns",
            "isOpenEnded": True,
        },
    ]

    support_responses = [
        {
            "responseText": "Customer support team is incredibly knowledgeable and responsive",
            "isOpenEnded": True,
        },
        {
            "responseText": "Got help within 15 minutes via chat - amazing service",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support goes above and beyond to solve problems",
            "isOpenEnded": True,
        },
        {
            "responseText": "Documentation is thorough and support articles are really helpful",
            "isOpenEnded": True,
        },
    ]

    integration_responses = [
        {
            "responseText": "Seamless integration with all our existing tools and workflows",
            "isOpenEnded": True,
        },
        {
            "responseText": "API is well-documented and easy to implement",
            "isOpenEnded": True,
        },
        {
            "responseText": "Fits perfectly into our daily workflow without disruption",
            "isOpenEnded": True,
        },
        {
            "responseText": "Export functionality works exactly as expected with our systems",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What do you like most about our product?",
            "questionId": "q1",
            "responses": ui_design_responses + performance_responses + support_responses + integration_responses,
        }
    ]


def generate_negative_feedback_responses():
    """Generate genuine negative feedback across problem areas."""
    performance_issues = [
        {
            "responseText": "App crashes constantly when I try to upload files larger than 100MB",
            "isOpenEnded": True,
        },
        {
            "responseText": "Loading times are painfully slow - sometimes 30+ seconds for simple queries",
            "isOpenEnded": True,
        },
        {
            "responseText": "System goes down for maintenance way too often, always during business hours",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data syncing is unreliable - lost work multiple times due to sync failures",
            "isOpenEnded": True,
        },
        {
            "responseText": "Memory usage is insane - laptop becomes unusable when running your app",
            "isOpenEnded": True,
        },
        {
            "responseText": "Frequent timeouts when working with larger datasets, very frustrating",
            "isOpenEnded": True,
        },
    ]

    support_problems = [
        {
            "responseText": "Support tickets take 3-5 days to get any response, completely unacceptable",
            "isOpenEnded": True,
        },
        {
            "responseText": "When support finally responds, they ask basic questions I already answered",
            "isOpenEnded": True,
        },
        {
            "responseText": "No phone support option - only slow email tickets for urgent issues",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support team clearly doesn't understand their own product features",
            "isOpenEnded": True,
        },
    ]

    pricing_concerns = [
        {
            "responseText": "Way overpriced compared to competitors offering similar features",
            "isOpenEnded": True,
        },
        {
            "responseText": "Hidden fees keep appearing - billing is not transparent at all",
            "isOpenEnded": True,
        },
        {
            "responseText": "Free tier is basically useless - forces you to upgrade immediately",
            "isOpenEnded": True,
        },
        {
            "responseText": "Poor value for money - paying premium prices for basic functionality",
            "isOpenEnded": True,
        },
    ]

    missing_features = [
        {
            "responseText": "No bulk operations - have to do everything one by one, super tedious",
            "isOpenEnded": True,
        },
        {
            "responseText": "Missing basic export options that every competitor has",
            "isOpenEnded": True,
        },
        {
            "responseText": "No offline mode - completely useless when internet is spotty",
            "isOpenEnded": True,
        },
        {
            "responseText": "Collaboration features are primitive compared to modern standards",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What issues or problems have you encountered with our product?",
            "questionId": "q1",
            "responses": performance_issues + support_problems + pricing_concerns + missing_features,
        }
    ]


def generate_multi_question_responses():
    """Generate responses for multiple questions with varied feedback types."""
    positive_responses = [
        # Ease of use feedback
        {
            "responseText": "Incredibly intuitive interface - figured it out in minutes",
            "isOpenEnded": True,
        },
        {
            "responseText": "Simple workflow that doesn't require extensive training",
            "isOpenEnded": True,
        },
        {
            "responseText": "Clean design makes complex tasks feel manageable",
            "isOpenEnded": True,
        },
        {
            "responseText": "Onboarding process was smooth and well-guided",
            "isOpenEnded": True,
        },
        {
            "responseText": "Everything is where you'd expect it to be",
            "isOpenEnded": True,
        },
        {
            "responseText": "No steep learning curve unlike other similar tools",
            "isOpenEnded": True,
        },
        {
            "responseText": "User experience feels thoughtfully designed",
            "isOpenEnded": True,
        },
        {
            "responseText": "Great balance of powerful features without complexity",
            "isOpenEnded": True,
        },
        # Reliability feedback
        {
            "responseText": "Rock solid performance - never had any crashes or issues",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data integrity is excellent, never lost any work",
            "isOpenEnded": True,
        },
        {
            "responseText": "Consistent uptime - can always rely on it being available",
            "isOpenEnded": True,
        },
        {
            "responseText": "Fast loading and response times across all features",
            "isOpenEnded": True,
        },
        {
            "responseText": "Auto-save functionality has saved me multiple times",
            "isOpenEnded": True,
        },
        {
            "responseText": "Handles large amounts of data without slowing down",
            "isOpenEnded": True,
        },
    ]

    improvement_responses = [
        # Advanced features
        {
            "responseText": "Need bulk operations for managing hundreds of items at once",
            "isOpenEnded": True,
        },
        {
            "responseText": "Advanced filtering and search capabilities would be game-changing",
            "isOpenEnded": True,
        },
        {
            "responseText": "API access for custom integrations with our internal tools",
            "isOpenEnded": True,
        },
        {
            "responseText": "Custom dashboards and reporting features for management",
            "isOpenEnded": True,
        },
        {
            "responseText": "Automation rules and workflows to reduce manual work",
            "isOpenEnded": True,
        },
        {
            "responseText": "More granular permission controls for team management",
            "isOpenEnded": True,
        },
        {
            "responseText": "Advanced analytics and insights into usage patterns",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better collaboration tools for larger teams",
            "isOpenEnded": True,
        },
        {
            "responseText": "White-label options for client-facing implementations",
            "isOpenEnded": True,
        },
        # Mobile improvements
        {
            "responseText": "Mobile app needs significant performance improvements",
            "isOpenEnded": True,
        },
        {
            "responseText": "Offline mode for working without internet connection",
            "isOpenEnded": True,
        },
        {
            "responseText": "Native mobile apps instead of web-based mobile experience",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better mobile interface optimization for small screens",
            "isOpenEnded": True,
        },
        {
            "responseText": "Faster loading times on mobile devices",
            "isOpenEnded": True,
        },
        {
            "responseText": "Push notifications for mobile app would be useful",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dark mode theme option for better user experience",
            "isOpenEnded": True,
        },
        {
            "responseText": "Keyboard shortcuts for power users on desktop",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better browser compatibility, especially for older versions",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What do you like about our product?",
            "questionId": "q1",
            "responses": positive_responses,
        },
        {
            "questionName": "What could we improve or add?",
            "questionId": "q2",
            "responses": improvement_responses,
        },
    ]


def generate_service_feedback_responses():
    """Generate customer service feedback with varied quality levels."""
    excellent_service = [
        {
            "responseText": "Customer support resolved my issue within 2 hours - absolutely fantastic",
            "isOpenEnded": True,
        },
        {
            "responseText": "Representative was knowledgeable and patient, walked me through everything step by step",
            "isOpenEnded": True,
        },
        {
            "responseText": "24/7 chat support is a game changer for our international team",
            "isOpenEnded": True,
        },
        {
            "responseText": "Proactive communication about updates and maintenance - really appreciate that",
            "isOpenEnded": True,
        },
        {
            "responseText": "Technical support team understood our complex setup immediately",
            "isOpenEnded": True,
        },
        {
            "responseText": "Follow-up email to ensure problem was fully resolved shows they care",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support documentation is comprehensive and easy to follow",
            "isOpenEnded": True,
        },
        {
            "responseText": "Video tutorials provided by support team were extremely helpful",
            "isOpenEnded": True,
        },
    ]

    moderate_service = [
        {
            "responseText": "Good service overall but had to wait 30 minutes for initial response",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support was helpful but had to explain the issue multiple times",
            "isOpenEnded": True,
        },
        {
            "responseText": "Eventually got the answer I needed, took a few back-and-forth messages",
            "isOpenEnded": True,
        },
        {
            "responseText": "Phone support was good but email responses are quite slow",
            "isOpenEnded": True,
        },
        {
            "responseText": "Representative was polite but didn't seem familiar with advanced features",
            "isOpenEnded": True,
        },
        {
            "responseText": "Got my problem solved but the process felt longer than necessary",
            "isOpenEnded": True,
        },
    ]

    poor_service = [
        {
            "responseText": "Waited over 2 hours for someone to respond to urgent issue",
            "isOpenEnded": True,
        },
        {
            "responseText": "First agent couldn't help, was transferred 3 times before getting answer",
            "isOpenEnded": True,
        },
        {
            "responseText": "Support ticket was closed without resolution, had to reopen",
            "isOpenEnded": True,
        },
        {
            "responseText": "Generic responses that didn't address my specific technical problem",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "How would you rate our customer service experience?",
            "questionId": "q1",
            "responses": excellent_service + moderate_service + poor_service,
        }
    ]


def generate_feature_request_responses():
    """Generate detailed feature requests across different categories."""
    integration_requests = [
        {
            "responseText": "Integration with Slack would revolutionize our team communication workflow",
            "isOpenEnded": True,
        },
        {
            "responseText": "Google Workspace SSO integration is desperately needed for enterprise deployment",
            "isOpenEnded": True,
        },
        {
            "responseText": "Zapier integration would allow us to automate so many manual processes",
            "isOpenEnded": True,
        },
        {
            "responseText": "Microsoft Teams integration for seamless file sharing and notifications",
            "isOpenEnded": True,
        },
        {
            "responseText": "API endpoints for custom reporting would enable our dashboard integrations",
            "isOpenEnded": True,
        },
        {
            "responseText": "Salesforce CRM integration to sync customer data automatically",
            "isOpenEnded": True,
        },
        {
            "responseText": "Webhook support for real-time data synchronization with our systems",
            "isOpenEnded": True,
        },
    ]

    mobile_improvements = [
        {
            "responseText": "Offline mode for mobile app would be incredible for field work",
            "isOpenEnded": True,
        },
        {
            "responseText": "Push notifications for important updates and deadlines",
            "isOpenEnded": True,
        },
        {
            "responseText": "Mobile photo upload with automatic compression and organization",
            "isOpenEnded": True,
        },
        {
            "responseText": "Better tablet interface optimized for larger screens",
            "isOpenEnded": True,
        },
        {
            "responseText": "Voice-to-text input for quick note taking on mobile",
            "isOpenEnded": True,
        },
        {
            "responseText": "Dark mode theme for mobile app to reduce eye strain",
            "isOpenEnded": True,
        },
    ]

    analytics_reporting = [
        {
            "responseText": "Advanced analytics dashboard with customizable KPI tracking",
            "isOpenEnded": True,
        },
        {
            "responseText": "Automated report scheduling and email delivery to stakeholders",
            "isOpenEnded": True,
        },
        {
            "responseText": "Data export in more formats like Excel, PDF, and CSV",
            "isOpenEnded": True,
        },
        {
            "responseText": "Real-time collaboration analytics to track team productivity",
            "isOpenEnded": True,
        },
        {
            "responseText": "Historical trend analysis with predictive insights",
            "isOpenEnded": True,
        },
    ]

    ux_improvements = [
        {
            "responseText": "Keyboard shortcuts for power users would dramatically improve efficiency",
            "isOpenEnded": True,
        },
        {
            "responseText": "Multi-language support for our international team members",
            "isOpenEnded": True,
        },
        {
            "responseText": "Bulk operations for managing large datasets more efficiently",
            "isOpenEnded": True,
        },
        {
            "responseText": "Template system for recurring workflows and standardized processes",
            "isOpenEnded": True,
        },
    ]

    return [
        {
            "questionName": "What features would you like to see added or improved?",
            "questionId": "q1",
            "responses": integration_requests + mobile_improvements + analytics_reporting + ux_improvements,
        }
    ]


@pytest.fixture
async def create_test_surveys(demo_org_team_user):
    """Create test surveys for evaluation with questions matching test data."""
    _, team, user = demo_org_team_user

    test_surveys = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    # Survey configs: (name, questions) - questions match the test data generators
    survey_configs = [
        # Test case 0: generate_test_data_responses() - 1 question
        (
            f"Test Survey with Placeholder Data {timestamp}",
            [
                {"type": "open", "question": "What do you think about our product?", "id": str(uuid.uuid4())},
            ],
        ),
        # Test case 1: generate_mixed_data_responses() - 1 question
        (
            f"Mixed Data Survey {timestamp}",
            [
                {"type": "open", "question": "How can we improve our product?", "id": str(uuid.uuid4())},
            ],
        ),
        # Test case 2: generate_positive_feedback_responses() - 1 question
        (
            f"Customer Satisfaction Survey {timestamp}",
            [
                {"type": "open", "question": "What do you like most about our product?", "id": str(uuid.uuid4())},
            ],
        ),
        # Test case 3: generate_negative_feedback_responses() - 1 question
        (
            f"Product Issues Survey {timestamp}",
            [
                {
                    "type": "open",
                    "question": "What issues or problems have you encountered with our product?",
                    "id": str(uuid.uuid4()),
                },
            ],
        ),
        # Test case 4: generate_multi_question_responses() - 2 questions
        (
            f"Comprehensive Feedback Survey {timestamp}",
            [
                {"type": "open", "question": "What do you like about our product?", "id": str(uuid.uuid4())},
                {"type": "open", "question": "What could we improve or add?", "id": str(uuid.uuid4())},
            ],
        ),
        # Test case 5: generate_service_feedback_responses() - 1 question
        (
            f"Support Service Survey {timestamp}",
            [
                {
                    "type": "open",
                    "question": "How would you rate our customer service experience?",
                    "id": str(uuid.uuid4()),
                },
            ],
        ),
        # Test case 6: generate_feature_request_responses() - 1 question
        (
            f"Feature Requests Survey {timestamp}",
            [
                {
                    "type": "open",
                    "question": "What features would you like to see added or improved?",
                    "id": str(uuid.uuid4()),
                },
            ],
        ),
    ]

    for name, questions in survey_configs:
        survey = await Survey.objects.acreate(
            team=team,
            created_by=user,
            name=name,
            description=f"Test survey: {name}",
            questions=questions,
            type="popover",
        )
        test_surveys.append(survey)

    return test_surveys


def _extract_response_texts(formatted_responses: list[dict]) -> dict[int, list[str]]:
    """
    Extract response texts from formatted_responses grouped by question index.
    Returns a dict mapping question index to list of response texts.
    """
    result: dict[int, list[str]] = {}
    for idx, question_group in enumerate(formatted_responses):
        responses = question_group.get("responses", [])
        result[idx] = [r.get("responseText", "") for r in responses if r.get("responseText")]
    return result


@pytest.fixture
async def call_survey_analysis_tool(demo_org_team_user, create_test_surveys):
    """
    This fixture creates a properly configured SurveyAnalysisTool for evaluation.
    Mocks fetch_responses to return the test data from formatted_responses.
    """
    _, team, user = demo_org_team_user
    test_surveys = create_test_surveys

    async def call_analysis_tool(context: dict) -> dict:
        """
        Call the survey analysis tool with provided context and return structured output.
        """
        try:
            # Get the right survey for the test case
            survey_index = context.get("survey_index", 0)
            if survey_index >= len(test_surveys):
                return {
                    "success": False,
                    "user_message": "Survey index out of range",
                    "artifact": None,
                    "error": "Invalid survey_index",
                }

            survey = test_surveys[survey_index]
            formatted_responses = context.get("formatted_responses", [])

            # Extract response texts grouped by question index for mocking
            responses_by_question = _extract_response_texts(formatted_responses)

            # Mock fetch_responses to return our test data
            def mock_fetch_responses(survey_id, question_index, question_id, start_date, end_date, team, limit=50):
                return responses_by_question.get(question_index, [])

            # Create the analysis tool
            analysis_tool = SurveyAnalysisTool(
                team=team,
                user=user,
                state=AssistantState(messages=[]),
                config=RunnableConfig(configurable={}),
            )

            # Call the tool with mocked fetch_responses
            with patch("products.surveys.backend.max_tools.fetch_responses", side_effect=mock_fetch_responses):
                result = await analysis_tool._arun_impl(survey_id=str(survey.id))

            # Return structured output
            user_message, artifact = result
            return {
                "success": True,
                "user_message": user_message,
                "artifact": artifact,
            }

        except Exception as e:
            return {
                "success": False,
                "user_message": f"❌ Analysis failed: {str(e)}",
                "artifact": None,
                "error": str(e),
            }

    return call_analysis_tool


class AnalysisPromptQualityScorer(LLMClassifier):
    """
    Evaluate if the tool output provides good context for the agent to analyze.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="analysis_prompt_quality",
            prompt_template="""
Evaluate whether the tool output provides sufficient context for an AI agent to analyze the survey responses.

Tool Output Message: {{output.user_message}}
Input Responses: {{input.formatted_responses}}

Evaluation Criteria:
1. **Survey Context**: Does the output include the survey name and response count?
2. **Response Clarity**: Are the responses clearly presented and readable?
3. **Analysis Instructions**: Does the output guide the agent on what to analyze (themes, sentiment, insights)?
4. **Completeness**: Does the output include all necessary information for meaningful analysis?
5. **Structure**: Is the output well-structured for agent consumption?

How would you rate the analysis prompt quality? Choose one:
- excellent: Output provides complete context with clear analysis instructions
- good: Output provides most necessary context with minor gaps
- adequate: Output has basic information but lacks clear structure or instructions
- poor: Output is incomplete, unclear, or missing key analysis guidance
""".strip(),
            choice_scores={
                "excellent": 1.0,
                "good": 0.75,
                "adequate": 0.5,
                "poor": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Retrieval failed", "error": output.get("error", "Unknown error")},
            )
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Retrieval failed", "error": output.get("error", "Unknown error")},
            )
        return super()._run_eval_sync(output, expected, **kwargs)


@pytest.mark.django_db
async def eval_survey_analysis(call_survey_analysis_tool, pytestconfig):
    """
    Evaluation for survey response retrieval functionality.
    Tests that the tool correctly retrieves and formats survey responses for agent analysis.
    """
    await MaxPublicEval(
        experiment_name="survey_analysis",
        task=call_survey_analysis_tool,
        scores=[
            AnalysisPromptQualityScorer(),
        ],
        data=[
            # Test Case 1: Small dataset (2 responses)
            EvalCase(
                input={
                    "survey_index": 0,
                    "formatted_responses": generate_test_data_responses(),
                },
                expected={
                    "response_count": 2,
                },
                metadata={"test_type": "small_dataset"},
            ),
            # Test Case 2: Mixed feedback (10 responses)
            EvalCase(
                input={
                    "survey_index": 1,
                    "formatted_responses": generate_mixed_data_responses(),
                },
                expected={
                    "response_count": 10,
                },
                metadata={"test_type": "mixed_feedback"},
            ),
            # Test Case 3: Positive feedback (20 responses)
            EvalCase(
                input={
                    "survey_index": 2,
                    "formatted_responses": generate_positive_feedback_responses(),
                },
                expected={
                    "response_count": 20,
                },
                metadata={"test_type": "positive_feedback"},
            ),
            # Test Case 4: Negative feedback (18 responses)
            EvalCase(
                input={
                    "survey_index": 3,
                    "formatted_responses": generate_negative_feedback_responses(),
                },
                expected={
                    "response_count": 18,
                },
                metadata={"test_type": "negative_feedback"},
            ),
            # Test Case 5: Multiple questions (33 total responses across 2 questions)
            EvalCase(
                input={
                    "survey_index": 4,
                    "formatted_responses": generate_multi_question_responses(),
                },
                expected={
                    "response_count": 33,
                },
                metadata={"test_type": "multi_question"},
            ),
            # Test Case 6: Service feedback (18 responses)
            EvalCase(
                input={
                    "survey_index": 5,
                    "formatted_responses": generate_service_feedback_responses(),
                },
                expected={
                    "response_count": 18,
                },
                metadata={"test_type": "service_feedback"},
            ),
            # Test Case 7: Feature requests (22 responses)
            EvalCase(
                input={
                    "survey_index": 6,
                    "formatted_responses": generate_feature_request_responses(),
                },
                expected={
                    "response_count": 22,
                },
                metadata={"test_type": "feature_requests"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
