from django.test import TestCase
from posthog.models.feedback.survey import Survey, update_question_stable_indices
from posthog.models.team import Team
from posthog.models.organization import Organization
import uuid


class TestSurveyStableIndices(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def test_new_survey_assigns_sequential_indices(self):
        """Test that a new survey gets sequential stable indices starting from 0"""
        survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1"},
                {"type": "open", "question": "Question 2"},
                {"type": "open", "question": "Question 3"},
            ],
        )

        # Function should assign stable indices 0, 1, 2
        update_question_stable_indices(None, survey)

        # Check that indices are sequential
        self.assertEqual(survey.questions[0]["stable_index"], 0)
        self.assertEqual(survey.questions[1]["stable_index"], 1)
        self.assertEqual(survey.questions[2]["stable_index"], 2)
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_existing_survey_preserves_indices(self):
        """Test that existing stable indices are preserved when updating a survey"""
        # Create and save a survey first
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 1},
                {"type": "open", "question": "Question 3", "stable_index": 2},
            ],
        )

        # Now modify the order of questions but keep the stable indices
        survey.questions = [
            {"type": "open", "question": "Question 3", "stable_index": 2},
            {"type": "open", "question": "Question 1", "stable_index": 0},
            {"type": "open", "question": "Question 2", "stable_index": 1},
        ]

        update_question_stable_indices(None, survey)

        # Stable indices should be preserved despite reordering
        self.assertEqual(survey.questions[0]["stable_index"], 2)
        self.assertEqual(survey.questions[1]["stable_index"], 0)
        self.assertEqual(survey.questions[2]["stable_index"], 1)
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_adding_new_questions(self):
        """Test that new questions get assigned new stable indices"""
        # Create and save a survey first
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 1},
            ],
        )

        # Now add a new question without a stable index
        survey.questions.append({"type": "open", "question": "Question 3"})

        update_question_stable_indices(None, survey)

        # New question should get stable_index = 2
        self.assertEqual(survey.questions[0]["stable_index"], 0)
        self.assertEqual(survey.questions[1]["stable_index"], 1)
        self.assertEqual(survey.questions[2]["stable_index"], 2)
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_removing_questions(self):
        """Test that max_question_stable_index is preserved when removing questions"""
        # Create and save a survey first
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 1},
                {"type": "open", "question": "Question 3", "stable_index": 2},
            ],
        )

        # Now remove the middle question
        survey.questions = [
            {"type": "open", "question": "Question 1", "stable_index": 0},
            {"type": "open", "question": "Question 3", "stable_index": 2},
        ]

        update_question_stable_indices(None, survey)

        # max_question_stable_index should still be 2
        self.assertEqual(survey.questions[0]["stable_index"], 0)
        self.assertEqual(survey.questions[1]["stable_index"], 2)
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_no_questions(self):
        """Test handling a survey with no questions"""
        survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[],
        )

        update_question_stable_indices(None, survey)

        self.assertEqual(survey.max_question_stable_index, 0)

    def test_mixed_questions_with_and_without_indices(self):
        """Test handling a mix of questions with and without stable indices"""
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 5},
                {"type": "open", "question": "Question 2"},
                {"type": "open", "question": "Question 3", "stable_index": 10},
                {"type": "open", "question": "Question 4"},
            ],
        )

        update_question_stable_indices(None, survey)

        # Existing indices should be preserved, new ones should be assigned
        self.assertEqual(survey.questions[0]["stable_index"], 5)
        self.assertEqual(survey.questions[2]["stable_index"], 10)

        # The new indices should be greater than the existing max
        self.assertGreater(survey.questions[1]["stable_index"], 10)
        self.assertGreater(survey.questions[3]["stable_index"], survey.questions[1]["stable_index"])
        self.assertEqual(survey.max_question_stable_index, survey.questions[3]["stable_index"])

    def test_duplicate_stable_indices(self):
        """Test handling duplicate stable indices - they should be fixed automatically"""
        survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 0},  # Duplicate!
                {"type": "open", "question": "Question 3"},
            ],
            id=uuid.uuid4(),  # Simulate an existing survey
        )

        # Mock the database lookup to return a survey with max_question_stable_index=0
        original_survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Original Question", "stable_index": 0},
            ],
            max_question_stable_index=0,
        )

        # Patch the get method to return our mocked survey
        original_get = Survey.objects.get

        def mocked_get(*args, **kwargs):
            return original_survey

        try:
            Survey.objects.get = mocked_get
            update_question_stable_indices(None, survey)
        finally:
            Survey.objects.get = original_get

        # Our function should fix the duplicate by assigning a new index
        self.assertEqual(survey.questions[0]["stable_index"], 0)
        self.assertEqual(survey.questions[1]["stable_index"], 1)  # Should be fixed to 1
        self.assertEqual(survey.questions[2]["stable_index"], 2)  # Gets max+1
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_existing_survey_without_indices(self):
        """Test adding stable indices to an existing survey that doesn't have them"""
        # Create a survey with no stable indices
        survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1"},
                {"type": "open", "question": "Question 2"},
                {"type": "open", "question": "Question 3"},
            ],
            id=uuid.uuid4(),  # Simulate an existing survey
        )

        # Mock the database lookup
        original_survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1"},
                {"type": "open", "question": "Question 2"},
                {"type": "open", "question": "Question 3"},
            ],
            max_question_stable_index=None,
        )

        # Patch the get method
        original_get = Survey.objects.get

        def mocked_get(*args, **kwargs):
            return original_survey

        try:
            Survey.objects.get = mocked_get
            update_question_stable_indices(None, survey)
        finally:
            Survey.objects.get = original_get

        # Should assign sequential indices
        self.assertEqual(survey.questions[0]["stable_index"], 0)
        self.assertEqual(survey.questions[1]["stable_index"], 1)
        self.assertEqual(survey.questions[2]["stable_index"], 2)
        self.assertEqual(survey.max_question_stable_index, 2)

    def test_complex_editing_scenario(self):
        """Test a complex scenario with reordering, adding, and removing questions"""
        # Start with a survey with stable indices
        survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 1},
                {"type": "open", "question": "Question 3", "stable_index": 2},
                {"type": "open", "question": "Question 4", "stable_index": 3},
            ],
            id=uuid.uuid4(),  # Simulate an existing survey
            max_question_stable_index=3,
        )

        # Mock the database lookup
        original_survey = Survey(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {"type": "open", "question": "Question 1", "stable_index": 0},
                {"type": "open", "question": "Question 2", "stable_index": 1},
                {"type": "open", "question": "Question 3", "stable_index": 2},
                {"type": "open", "question": "Question 4", "stable_index": 3},
            ],
            max_question_stable_index=3,
        )

        # Now simulate a complex edit:
        # - Remove Question 2
        # - Add two new questions
        # - Reorder the remaining questions
        survey.questions = [
            {"type": "open", "question": "Question 4", "stable_index": 3},
            {"type": "open", "question": "New Question A"},
            {"type": "open", "question": "Question 1", "stable_index": 0},
            {"type": "open", "question": "New Question B"},
            {"type": "open", "question": "Question 3", "stable_index": 2},
        ]

        # Patch the get method
        original_get = Survey.objects.get

        def mocked_get(*args, **kwargs):
            return original_survey

        try:
            Survey.objects.get = mocked_get
            update_question_stable_indices(None, survey)
        finally:
            Survey.objects.get = original_get

        # Existing indices should be preserved
        self.assertEqual(survey.questions[0]["stable_index"], 3)  # Question 4
        self.assertEqual(survey.questions[2]["stable_index"], 0)  # Question 1
        self.assertEqual(survey.questions[4]["stable_index"], 2)  # Question 3

        # New questions should get new indices
        self.assertEqual(survey.questions[1]["stable_index"], 4)  # New Question A
        self.assertEqual(survey.questions[3]["stable_index"], 5)  # New Question B

        # max_question_stable_index should be updated
        self.assertEqual(survey.max_question_stable_index, 5)

    def patch_get_object(self, model_class, return_value):
        """Helper method to patch the objects.get method"""
        original_get = model_class.objects.get

        def mocked_get(*args, **kwargs):
            return return_value

        model_class.objects.get = mocked_get
        try:
            yield
        finally:
            model_class.objects.get = original_get
