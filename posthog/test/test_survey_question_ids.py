from posthog.test.base import BaseTest

from posthog.models.surveys.survey import Survey


class TestSurveyQuestionIds(BaseTest):
    def test_questions_get_ids_on_creation(self):
        """Test that questions get IDs assigned when a survey is created."""
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {
                    "type": "open",
                    "question": "What do you think of this feature?",
                },
                {
                    "type": "rating",
                    "question": "How would you rate this feature?",
                    "scale": 5,
                },
            ],
        )

        # Refresh from DB to ensure we get the updated questions
        survey.refresh_from_db()

        # Check that all questions have IDs
        for question in survey.questions:
            self.assertIn("id", question)
            self.assertIsNotNone(question["id"])
            self.assertTrue(len(question["id"]) > 0)

    def test_existing_question_ids_are_preserved(self):
        """Test that existing question IDs are preserved when a survey is updated."""
        # Create a survey with questions that already have IDs
        existing_id_1 = "existing-id-1"
        existing_id_2 = "existing-id-2"

        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[
                {
                    "type": "open",
                    "question": "What do you think of this feature?",
                    "id": existing_id_1,
                },
                {
                    "type": "rating",
                    "question": "How would you rate this feature?",
                    "scale": 5,
                    "id": existing_id_2,
                },
            ],
        )

        # Update the survey with a mix of questions with and without IDs
        survey.questions = [
            {
                "type": "open",
                "question": "Updated question 1",
                "id": existing_id_1,  # Keep existing ID
            },
            {
                "type": "rating",
                "question": "Updated question 2",
                "scale": 5,
                # No ID provided, should get a new one
            },
            {
                "type": "open",
                "question": "New question",
                # No ID provided, should get a new one
            },
        ]
        survey.save()

        # Refresh from DB
        survey.refresh_from_db()

        # Check that all questions have IDs
        self.assertEqual(len(survey.questions), 3)

        # First question should keep its existing ID
        self.assertEqual(survey.questions[0]["id"], existing_id_1)

        # Second and third questions should have new IDs
        self.assertIn("id", survey.questions[1])
        self.assertIsNotNone(survey.questions[1]["id"])
        self.assertNotEqual(survey.questions[1]["id"], existing_id_2)  # Should not reuse the old ID

        self.assertIn("id", survey.questions[2])
        self.assertIsNotNone(survey.questions[2]["id"])

    def test_empty_questions_handled_gracefully(self):
        """Test that empty questions list is handled gracefully."""
        # Create a survey with no questions
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey",
            type="popover",
            questions=[],
        )

        # This should not raise an error
        survey.save()

        # Create a survey with null questions
        survey = Survey.objects.create(
            team=self.team,
            name="Test Survey 2",
            type="popover",
            questions=None,
        )

        # This should not raise an error
        survey.save()
