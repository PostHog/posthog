"""
Simple async test for the survey creation MaxTool.
"""

import os

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import django.utils.timezone

from asgiref.sync import sync_to_async
from langchain_core.runnables import RunnableConfig

from posthog.schema import SurveyCreationSchema, SurveyQuestionSchema, SurveyQuestionType, SurveyType

from posthog.models import FeatureFlag, Survey

from ee.hogai.graph.root.tools.create_survey import (
    CreateSurveyTool,
    SurveyLoopNode,
    SurveyToolkit,
    get_team_survey_config,
)

OPENAI_PATCH_PATH = "products.surveys.backend.max_tools.MaxChatOpenAI"


class TestSurveyCreatorTool(BaseTest):
    def setUp(self):
        super().setUp()
        # Set mock OpenAI API key for tests
        os.environ["OPENAI_API_KEY"] = "test-api-key"
        self._config: RunnableConfig = {
            "configurable": {
                "team": self.team,
                "user": self.user,
            },
        }

    def tearDown(self):
        super().tearDown()
        # Clean up the mock API key
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

    def _setup_tool(self):
        """Helper to create a SurveyCreatorTool instance with mocked dependencies"""
        tool = CreateSurveyTool(team=self.team, user=self.user, config=self._config, tool_call_id="test-tool-call-id")
        return tool

    def test_get_team_survey_config(self):
        """Test team survey configuration function"""

        config = get_team_survey_config(self.team)

        assert "appearance" in config
        assert "default_settings" in config
        assert config["default_settings"]["type"] == "popover"

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_success(self, mock_create_survey):
        """Test successful survey creation through _arun_impl"""
        tool = self._setup_tool()

        # Mock the LLM response
        mock_output = SurveyCreationSchema(
            name="Test Survey",
            description="A simple test survey",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="How do you feel about our product?",
                    description="Please share your thoughts",
                    optional=False,
                )
            ],
            should_launch=False,
            enable_partial_responses=True,
        )

        # Set up the mock to return our test data
        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a test survey")

        # Verify success response
        self.assertIn("✅ Survey", content)
        self.assertIn("created", content)
        self.assertIn("successfully", content)
        self.assertIn("survey_id", artifact)
        self.assertIn("survey_name", artifact)

        # Verify survey was created in database
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        self.assertEqual(survey.name, "Test Survey")
        self.assertEqual(survey.description, "A simple test survey")
        self.assertEqual(survey.type, "popover")
        self.assertIsInstance(survey.questions, list)
        assert isinstance(survey.questions, list)
        self.assertEqual(len(survey.questions), 1)
        self.assertFalse(survey.archived)

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_no_questions_validation(self, mock_create_survey):
        """Test validation error when no questions are provided"""
        tool = self._setup_tool()

        # Mock LLM response with no questions
        mock_output = SurveyCreationSchema(
            name="Test Survey",
            description="A test survey",
            type=SurveyType.POPOVER,
            questions=[],  # Empty questions list
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey")

        # Verify error response
        self.assertIn("❌ Survey must have at least one question", content)
        self.assertEqual(artifact["error"], "validation_failed")
        self.assertIn("No questions were created from the survey instructions", artifact["error_message"])

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_arun_impl_with_launch(self, mock_create_survey):
        """Test survey creation with immediate launch"""
        tool = self._setup_tool()

        # Mock the LLM response with launch=True
        mock_output = SurveyCreationSchema(
            name="Launch Survey",
            description="A survey to launch",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="Test question?",
                    optional=False,
                )
            ],
            should_launch=True,  # This should launch the survey
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create and launch a survey")

        # Verify success response with launch message
        self.assertIn("✅ Survey", content)
        self.assertIn("successfully", content)

        # Verify survey was created and launched
        survey = await sync_to_async(Survey.objects.get)(id=artifact["survey_id"])
        self.assertIsNotNone(survey.start_date)  # Should have a start date when launched

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag(self, mock_create_survey):
        """Test creating a survey with a linked feature flag"""
        tool = self._setup_tool()

        # Create a test feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="test-feature",
            name="Test Feature",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Mock the LLM response with linked flag
        mock_output = SurveyCreationSchema(
            name="Feature Flag Survey",
            description="Survey for users with test feature",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.RATING,
                    question="How satisfied are you with the new feature?",
                    scale=5,
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for users with test-feature flag")

        # Verify success response
        self.assertIn("✅ Survey", content)
        self.assertIn("successfully", content)

        # Verify survey was created with feature flag
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        self.assertEqual(survey.name, "Feature Flag Survey")
        self.assertEqual(survey.linked_flag_id, flag.id)

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant(self, mock_create_survey):
        """Test creating a survey with a feature flag variant"""
        tool = self._setup_tool()

        # Create a multivariate feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="ab-test-feature",
            name="A/B Test Feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "treatment", "rollout_percentage": 50},
                    ]
                },
            },
        )

        # Mock the LLM response with linked flag and variant
        mock_output = SurveyCreationSchema(
            name="A/B Test Control Survey",
            description="Survey for users in control variant",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.SINGLE_CHOICE,
                    question="Which version do you prefer?",
                    choices=["Version A", "Version B", "No preference"],
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            conditions={"linkedFlagVariant": "control"},
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for users in control variant of ab-test-feature")

        # Verify success response
        assert "✅ Survey" in content
        assert "successfully" in content

        # Verify survey was created with feature flag and variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        self.assertEqual(survey.name, "A/B Test Control Survey")
        self.assertEqual(survey.linked_flag_id, flag.id)
        assert survey.conditions is not None
        self.assertEqual(survey.conditions["linkedFlagVariant"], "control")

    @patch.object(CreateSurveyTool, "_create_survey_from_instructions")
    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_create_survey_with_feature_flag_variant_any(self, mock_create_survey):
        """Test creating a survey with linkedFlagVariant set to 'any'"""
        tool = self._setup_tool()

        # Create a multivariate feature flag
        flag = await sync_to_async(FeatureFlag.objects.create)(
            team=self.team,
            key="multivariate-feature",
            name="Multivariate Feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant-a", "rollout_percentage": 33},
                        {"key": "variant-b", "rollout_percentage": 33},
                        {"key": "variant-c", "rollout_percentage": 34},
                    ]
                },
            },
        )

        # Mock the LLM response with linked flag and 'any' variant
        mock_output = SurveyCreationSchema(
            name="All Variants Survey",
            description="Survey for all users with the feature enabled",
            type=SurveyType.POPOVER,
            questions=[
                SurveyQuestionSchema(
                    type=SurveyQuestionType.OPEN,
                    question="How is the new feature working for you?",
                    optional=False,
                )
            ],
            linked_flag_id=flag.id,
            conditions={"linkedFlagVariant": "any"},
            should_launch=False,
            enable_partial_responses=True,
        )

        mock_create_survey.return_value = mock_output

        # Run the method
        content, artifact = await tool._arun_impl("Create a survey for all users with multivariate-feature enabled")

        # Verify success response
        self.assertIn("✅ Survey", content)
        self.assertIn("successfully", content)

        # Verify survey was created with feature flag and 'any' variant
        survey = await sync_to_async(Survey.objects.select_related("linked_flag").get)(id=artifact["survey_id"])
        self.assertEqual(survey.name, "All Variants Survey")
        assert survey.conditions is not None
        self.assertEqual(survey.conditions["linkedFlagVariant"], "any")


class TestSurveyLoopNode(BaseTest):
    def setUp(self):
        super().setUp()

    def _setup_node(self):
        """Helper to create a TestSurveyLoopNode instance"""
        return SurveyLoopNode(team=self.team, user=self.user, toolkit_class=SurveyToolkit)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_empty(self):
        """Test getting existing surveys summary when no surveys exist"""
        node = self._setup_node()

        summary = await node._get_existing_surveys_summary()

        assert summary == "No existing surveys"

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_with_surveys(self):
        """Test getting existing surveys summary with existing surveys"""
        node = self._setup_node()

        # Create test surveys
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Draft Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        # Create an active survey (with start_date but no end_date)
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Active Survey",
            type="email",
            questions=[{"type": "rating", "question": "How satisfied?", "scale": 5}],
            created_by=self.user,
            start_date=django.utils.timezone.now(),
        )

        summary = await node._get_existing_surveys_summary()

        # Verify both surveys are included
        self.assertIn("Draft Survey", summary)
        self.assertIn("Active Survey", summary)
        self.assertIn("draft", summary)
        self.assertIn("active", summary)
        self.assertIn("popover", summary)
        self.assertIn("email", summary)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_excludes_archived(self):
        """Test that archived surveys are excluded from the summary"""
        node = self._setup_node()

        # Create a regular survey
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Regular Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
        )

        # Create an archived survey (should be excluded)
        await sync_to_async(Survey.objects.create)(
            team=self.team,
            name="Archived Survey",
            type="popover",
            questions=[{"type": "open", "question": "Test?"}],
            created_by=self.user,
            archived=True,
        )

        summary = await node._get_existing_surveys_summary()

        # Only the non-archived survey should be included
        self.assertIn("Regular Survey", summary)
        self.assertNotIn("Archived Survey", summary)

    @pytest.mark.django_db
    @pytest.mark.asyncio
    async def test_get_existing_surveys_summary_limits_to_five(self):
        """Test that the summary is limited to 5 surveys"""
        node = self._setup_node()

        # Create 6 surveys
        survey_names = []
        for i in range(6):
            name = f"Survey {i+1}"
            survey_names.append(name)
            await sync_to_async(Survey.objects.create)(
                team=self.team,
                name=name,
                type="popover",
                questions=[{"type": "open", "question": "Test?"}],
                created_by=self.user,
            )

        summary = await node._get_existing_surveys_summary()

        # Count the number of survey entries (lines starting with "- '")
        summary_lines = [line for line in summary.split("\n") if line.strip().startswith("- '")]
        self.assertEqual(len(summary_lines), 5)  # Should be limited to 5

        # Verify it contains survey information
        self.assertIn("Survey", summary)
        self.assertIn("draft", summary)
