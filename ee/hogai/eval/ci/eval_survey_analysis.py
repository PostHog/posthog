import uuid
import datetime

import pytest

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
    """Create test surveys for evaluation."""
    _, team, user = demo_org_team_user

    test_surveys = []
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    survey_names = [
        f"Test Survey with Placeholder Data {timestamp}",
        f"Mixed Data Survey {timestamp}",
        f"Customer Satisfaction Survey {timestamp}",
        f"Product Issues Survey {timestamp}",
        f"Comprehensive Feedback Survey {timestamp}",
        f"Support Service Survey {timestamp}",
        f"Feature Requests Survey {timestamp}",
    ]

    for name in survey_names:
        survey = await Survey.objects.acreate(
            team=team,
            created_by=user,
            name=name,
            description=f"Test survey: {name}",
            questions=[
                {"type": "open", "question": "What do you think?", "id": str(uuid.uuid4())},
                {"type": "open", "question": "Any other feedback?", "id": str(uuid.uuid4())},
            ],
            type="popover",
        )
        test_surveys.append(survey)

    return test_surveys


@pytest.fixture
async def call_survey_analysis_tool(demo_org_team_user, create_test_surveys):
    """
    This fixture creates a properly configured SurveyAnalysisTool for evaluation.
    """
    _, team, user = demo_org_team_user
    test_surveys = create_test_surveys

    async def call_analysis_tool(context: dict) -> dict:
        """
        Call the survey analysis tool with provided context and return structured output.
        """
        try:
            # Get the right survey ID for the test case
            survey_index = context.get("survey_index", 0)
            if survey_index < len(test_surveys):
                survey = test_surveys[survey_index]
                # Update context with real survey data
                context = {
                    **context,
                    "survey_id": str(survey.id),
                    "survey_name": survey.name,
                }

            # Create the analysis tool
            analysis_tool = SurveyAnalysisTool(
                team=team,
                user=user,
                state=AssistantState(messages=[]),
                config=RunnableConfig(configurable={"contextual_tools": {"analyze_survey_responses": context}}),
            )

            # Call the tool
            result = await analysis_tool._arun_impl()

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


class TestDataDetectionScorer(LLMClassifier):
    """
    Evaluate if the tool correctly identifies test/placeholder data vs genuine feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="test_data_detection",
            prompt_template="""
Evaluate whether the survey analysis tool correctly identified if the responses are test/placeholder data or genuine user feedback.

Survey Context:
Survey ID: {{output.artifact.survey_id}}
Survey Name: {{output.artifact.survey_name}}
Response Data: {{input.formatted_responses}}

Analysis Output:
User Message: {{output.user_message}}
Success: {{output.success}}

Expected Classification: {{expected.data_type}}

Evaluation Criteria:
1. **Correct Classification**: Did the tool correctly identify whether responses are test data or genuine feedback?
2. **Test Data Patterns**: For test data, did it identify patterns like "fasdfasdf", "abc", random keystrokes?
3. **Genuine Data Recognition**: For genuine feedback, did it avoid false positive test data detection?
4. **Appropriate Response**: Did the tool provide appropriate analysis or recommendations based on data quality?
5. **No Hallucination**: Did it avoid creating fictional themes from meaningless test responses?

Test data indicators: Random keystrokes, repeated "abc", "hello", "asdf", "fasdfasdf", etc.
Genuine data indicators: Coherent sentences, actual feedback, meaningful responses.

How accurately did the tool detect the data type? Choose one:
- perfect: Correctly identified data type and provided appropriate response
- good: Mostly correct identification with minor issues
- partial: Some correct aspects but missed key data quality indicators
- incorrect: Completely misclassified the data type or hallucinated analysis
""".strip(),
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "incorrect": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return super()._run_eval_sync(output, expected, **kwargs)


class ThemeExtractionQualityScorer(LLMClassifier):
    """
    Evaluate the quality of theme extraction from genuine user feedback.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="theme_extraction_quality",
            prompt_template="""
Evaluate the quality of themes extracted from survey responses.

Survey Responses: {{input.formatted_responses}}

Extracted Themes: {{output.artifact.analysis.themes}}
Analysis Insights: {{output.artifact.analysis.insights}}

Expected Themes: {{expected.expected_themes}}

Evaluation Criteria:
1. **Relevance**: Are the extracted themes actually present in the responses?
2. **Completeness**: Did the analysis capture the main themes from the responses?
3. **Accuracy**: Are the themes accurately representing what users said?
4. **Specificity**: Are themes specific enough to be actionable, not too generic?
5. **No Hallucination**: Are all themes based on actual response content?

Note: Themes don't need to match expected themes exactly, but should be legitimate interpretations of the response data.

How would you rate the theme extraction quality? Choose one:
- excellent: Themes are accurate, complete, and actionable based on actual responses
- good: Themes are mostly accurate with minor issues or omissions
- adequate: Some good themes but missing key patterns or slightly generic
- poor: Inaccurate themes, significant hallucination, or missed major patterns
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
        # Only evaluate if we have genuine data and successful analysis
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )

        # Skip for test data scenarios
        if expected and expected.get("data_type") == "test":
            return None

        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )

        # Skip for test data scenarios
        if expected and expected.get("data_type") == "test":
            return None

        return super()._run_eval_sync(output, expected, **kwargs)


class RecommendationQualityScorer(LLMClassifier):
    """
    Evaluate the quality and actionability of recommendations.
    """

    def __init__(self, **kwargs):
        super().__init__(
            name="recommendation_quality",
            prompt_template="""
Evaluate the quality of recommendations generated from survey analysis.

Survey Responses: {{input.formatted_responses}}
Generated Recommendations: {{output.artifact.analysis.recommendations}}

Evaluation Criteria:
1. **Actionability**: Are recommendations specific and actionable, not generic advice?
2. **Relevance**: Are recommendations directly based on the survey insights?
3. **Feasibility**: Are recommendations realistic for a product team to implement?
4. **Prioritization**: Are the most important recommendations prioritized appropriately?
5. **Clarity**: Are recommendations clear and well-articulated?

For test data scenarios: Recommendations should acknowledge data quality issues and suggest collecting genuine feedback.

How would you rate the recommendation quality? Choose one:
- excellent: Recommendations are highly actionable, relevant, and well-prioritized
- good: Recommendations are mostly actionable with minor issues
- adequate: Some good recommendations but could be more specific or better prioritized
- poor: Generic, irrelevant, or non-actionable recommendations
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
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected=None, **kwargs):
        if not output.get("success", False):
            return Score(
                name=self._name(),
                score=0,
                metadata={"reason": "Analysis failed", "error": output.get("error", "Unknown error")},
            )
        return super()._run_eval_sync(output, expected, **kwargs)


@pytest.mark.django_db
async def eval_survey_analysis(call_survey_analysis_tool, pytestconfig):
    """
    Evaluation for survey response analysis functionality.
    """
    await MaxPublicEval(
        experiment_name="survey_analysis",
        task=call_survey_analysis_tool,
        scores=[
            TestDataDetectionScorer(),
            ThemeExtractionQualityScorer(),
            RecommendationQualityScorer(),
        ],
        data=[
            # Test Case 1: Clear test data detection (20 responses)
            EvalCase(
                input={
                    "survey_index": 0,
                    "formatted_responses": generate_test_data_responses(),
                },
                expected={
                    "data_type": "test",
                    "should_detect_test_data": True,
                },
                metadata={"test_type": "test_data_detection"},
            ),
            # Test Case 2: Mixed test and genuine data (25 responses - 60% test, 40% genuine)
            EvalCase(
                input={
                    "survey_index": 1,
                    "formatted_responses": generate_mixed_data_responses(),
                },
                expected={
                    "data_type": "mixed",
                    "expected_themes": ["Interface/Navigation Issues", "Performance Problems"],
                },
                metadata={"test_type": "mixed_data"},
            ),
            # Test Case 3: Genuine positive feedback (20 responses across multiple themes)
            EvalCase(
                input={
                    "survey_index": 2,
                    "formatted_responses": generate_positive_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "User Interface & Design",
                        "Performance & Reliability",
                        "Customer Support",
                        "Integration & Workflow",
                    ],
                },
                metadata={"test_type": "positive_feedback"},
            ),
            # Test Case 4: Genuine negative feedback (18 responses across problem areas)
            EvalCase(
                input={
                    "survey_index": 3,
                    "formatted_responses": generate_negative_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Performance & Reliability",
                        "Customer Support Issues",
                        "Pricing & Value Concerns",
                        "Missing Features",
                    ],
                },
                metadata={"test_type": "negative_feedback"},
            ),
            # Test Case 5: Multiple questions with varied feedback (32 total responses)
            EvalCase(
                input={
                    "survey_index": 4,
                    "formatted_responses": generate_multi_question_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Ease of Use & Design",
                        "Reliability & Performance",
                        "Advanced Feature Requests",
                        "Mobile & Technical Improvements",
                    ],
                },
                metadata={"test_type": "multi_question_feedback"},
            ),
            # Test Case 6: Support and service feedback (18 responses)
            EvalCase(
                input={
                    "survey_index": 5,
                    "formatted_responses": generate_service_feedback_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Excellent Service",
                        "Response Time Issues",
                        "Knowledge Gaps",
                        "Communication Problems",
                    ],
                },
                metadata={"test_type": "service_feedback"},
            ),
            # Test Case 7: Feature requests and product development feedback (22 responses)
            EvalCase(
                input={
                    "survey_index": 6,
                    "formatted_responses": generate_feature_request_responses(),
                },
                expected={
                    "data_type": "genuine",
                    "expected_themes": [
                        "Integration Requests",
                        "Mobile Improvements",
                        "Analytics & Reporting",
                        "User Experience Enhancements",
                    ],
                },
                metadata={"test_type": "feature_requests"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
