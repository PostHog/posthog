from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db.models.signals import pre_save

from posthog.models import Survey
from posthog.models.surveys.survey import pre_save_survey


class TestAddQuestionIdsToSurveys(BaseTest):
    def setUp(self):
        super().setUp()

        # Disconnect the pre_save signal temporarily to create surveys without IDs
        pre_save.disconnect(pre_save_survey, sender=Survey)

        # Create test surveys with and without question IDs
        self.survey1 = Survey.objects.create(
            team=self.team,
            name="Survey with IDs",
            questions=[
                {"id": "existing-id-1", "type": "open", "question": "What do you think?"},
                {"id": "existing-id-2", "type": "rating", "question": "How would you rate us?"},
            ],
        )

        self.survey2 = Survey.objects.create(
            team=self.team,
            name="Survey without IDs",
            questions=[
                {"type": "open", "question": "What do you think?"},
                {"type": "rating", "question": "How would you rate us?"},
            ],
        )

        self.survey3 = Survey.objects.create(
            team=self.team,
            name="Survey with mixed IDs",
            questions=[
                {"id": "existing-id-3", "type": "open", "question": "What do you think?"},
                {"type": "rating", "question": "How would you rate us?"},
            ],
        )

        self.survey4 = Survey.objects.create(
            team=self.team,
            name="Survey with no questions",
            questions=[],
        )

        # Reconnect the pre_save signal
        pre_save.connect(pre_save_survey, sender=Survey)

    def test_add_question_ids_to_surveys_with_really_run(self):
        # Run the command with really-run flag
        call_command("add_question_ids_to_surveys", batch_size=2, really_run=True)

        # Refresh surveys from database
        self.survey1.refresh_from_db()
        self.survey2.refresh_from_db()
        self.survey3.refresh_from_db()
        self.survey4.refresh_from_db()

        # Check that all questions have IDs
        for question in self.survey1.questions:
            self.assertIn("id", question)
            # Original IDs should be preserved
            if question["question"] == "What do you think?":
                self.assertEqual(question["id"], "existing-id-1")
            elif question["question"] == "How would you rate us?":
                self.assertEqual(question["id"], "existing-id-2")

        for question in self.survey2.questions:
            self.assertIn("id", question)
            # These should have new UUIDs
            self.assertTrue(len(question["id"]) > 0)

        for question in self.survey3.questions:
            self.assertIn("id", question)
            # First question should keep its ID
            if question["question"] == "What do you think?":
                self.assertEqual(question["id"], "existing-id-3")
            # Second question should have a new UUID
            elif question["question"] == "How would you rate us?":
                self.assertTrue(len(question["id"]) > 0)

        # Survey with no questions should remain unchanged
        self.assertEqual(self.survey4.questions, [])

    def test_default_dry_run_mode(self):
        # Run the command without really-run flag (default dry-run mode)
        call_command("add_question_ids_to_surveys", batch_size=2)

        # Refresh surveys from database
        self.survey2.refresh_from_db()

        # Check that no changes were made in dry-run mode
        for question in self.survey2.questions:
            self.assertNotIn("id", question)

    def test_batch_processing(self):
        """
        Test that the command processes surveys in batches as expected.

        This test verifies that the command works correctly with a very small batch size,
        which indirectly confirms that batch processing is working.
        """
        # Create additional surveys for this test
        pre_save.disconnect(pre_save_survey, sender=Survey)

        # Create 10 surveys without question IDs for this test
        for i in range(10):
            Survey.objects.create(
                team=self.team,
                name=f"Batch Test Survey {i}",
                questions=[
                    {"type": "open", "question": f"Question {i}"},
                ],
            )

        pre_save.connect(pre_save_survey, sender=Survey)

        # Set a very small batch size to ensure multiple batches
        batch_size = 1

        # Run the command with a small batch size
        with patch("sys.stdout"):
            call_command("add_question_ids_to_surveys", batch_size=batch_size, really_run=True)

        # Verify that all surveys have question IDs now
        for survey in Survey.objects.filter(name__startswith="Batch Test Survey"):
            survey.refresh_from_db()
            for question in survey.questions:
                self.assertIn("id", question)
                self.assertTrue(len(question["id"]) > 0)

        # The fact that all surveys were processed with a batch size of 1
        # indirectly confirms that the batch processing logic works correctly
