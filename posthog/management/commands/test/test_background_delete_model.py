from unittest.mock import patch, MagicMock
from django.core.management.base import CommandError

from posthog.management.commands.background_delete_model import Command
from posthog.models.person.person import Person
from posthog.test.base import BaseTest


class TestBackgroundDeleteModel(BaseTest):
    def setUp(self):
        super().setUp()
        self.command = Command()

    def test_invalid_model_name_format(self):
        """Test that invalid model name format raises CommandError"""
        with self.assertRaises(CommandError) as context:
            self.command.handle("invalid_model_name", team_id=1)

        self.assertIn("Model name must be in format 'app_label.model_name'", str(context.exception))

    def test_model_not_found(self):
        """Test that non-existent model raises CommandError"""
        with self.assertRaises(CommandError) as context:
            self.command.handle("nonexistent.Model", team_id=1)

        self.assertIn("Model not found", str(context.exception))

    def test_model_without_team_field(self):
        """Test that model without team_id or team field raises CommandError"""
        # Create a mock model without team field
        with patch("django.apps.apps.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"

            # Mock the _meta.get_fields() to return no team-related fields
            mock_field = MagicMock()
            mock_field.name = "some_other_field"
            mock_model._meta.get_fields.return_value = [mock_field]

            mock_get_model.return_value = mock_model

            with self.assertRaises(CommandError) as context:
                self.command.handle("test.TestModel", team_id=1)

            self.assertIn("does not have a team_id or team field", str(context.exception))

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    def test_valid_model_with_team_id_field(self, mock_task):
        """Test that valid model with team_id field starts background task"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        # Create some test persons
        Person.objects.create(team=self.team, properties={})
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id)

        # Verify task was called
        mock_task.delay.assert_called_once_with(model_name="posthog.Person", team_id=self.team.id, batch_size=10000)

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    def test_custom_batch_size(self, mock_task):
        """Test that custom batch size is passed to task"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        self.command.handle("posthog.Person", team_id=self.team.id, batch_size=5000)

        mock_task.delay.assert_called_once_with(model_name="posthog.Person", team_id=self.team.id, batch_size=5000)

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    def test_dry_run_does_not_start_task(self, mock_task):
        """Test that dry run shows info but doesn't start task"""
        # Create some test persons
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id, dry_run=True)

        # Verify task was not called
        mock_task.delay.assert_not_called()

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    def test_model_with_team_foreign_key(self, mock_task):
        """Test that model with team ForeignKey works"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        # Create a mock model with team ForeignKey
        with patch("django.apps.apps.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"

            # Mock the _meta.get_fields() to return a field with name 'team'
            mock_field = MagicMock()
            mock_field.name = "team"
            mock_model._meta.get_fields.return_value = [mock_field]

            mock_model.objects.filter.return_value.count.return_value = 5
            mock_get_model.return_value = mock_model

            self.command.handle("test.TestModel", team_id=1)

            # Verify task was called
            mock_task.delay.assert_called_once_with(model_name="test.TestModel", team_id=1, batch_size=10000)
