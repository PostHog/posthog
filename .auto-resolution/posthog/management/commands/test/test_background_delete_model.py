from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError

from posthog.management.commands.background_delete_model import Command
from posthog.models.person.person import Person


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
    @patch("builtins.input", return_value="DELETE 2 RECORDS")
    def test_valid_model_with_team_id_field(self, mock_input, mock_task):
        """Test that valid model with team_id field starts background task"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        # Create some test persons
        Person.objects.create(team=self.team, properties={})
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id)

        # Verify task was called
        mock_task.delay.assert_called_once_with(
            model_name="posthog.Person", team_id=self.team.id, batch_size=10000, records_to_delete=2
        )

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    def test_dry_run_does_not_start_task(self, mock_task):
        """Test that dry run shows info but doesn't start task"""
        # Create some test persons
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id, dry_run=True)

        # Verify task was not called
        mock_task.delay.assert_not_called()

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    @patch("builtins.input", return_value="DELETE 5 RECORDS")
    def test_model_with_team_foreign_key(self, mock_input, mock_task):
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
            mock_task.delay.assert_called_once_with(
                model_name="test.TestModel", team_id=1, batch_size=10000, records_to_delete=5
            )

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    @patch("builtins.input", return_value="CANCEL")
    def test_confirmation_cancelled(self, mock_input, mock_task):
        """Test that task is not started when confirmation is cancelled"""
        # Create some test persons
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id)

        # Verify task was not called
        mock_task.delay.assert_not_called()

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    @patch("builtins.input", return_value="DELETE 1,000,000 RECORDS")
    def test_large_deletion_confirmation(self, mock_input, mock_task):
        """Test that large deletions require specific confirmation"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        # Create a mock model with many records
        with patch("django.apps.apps.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"

            # Mock the _meta.get_fields() to return a field with name 'team_id'
            mock_field = MagicMock()
            mock_field.name = "team_id"
            mock_model._meta.get_fields.return_value = [mock_field]

            # Mock a large count
            mock_model.objects.filter.return_value.count.return_value = 1000000
            mock_get_model.return_value = mock_model

            self.command.handle("test.TestModel", team_id=1)

            # Verify task was called
            mock_task.delay.assert_called_once_with(
                model_name="test.TestModel", team_id=1, batch_size=10000, records_to_delete=1000000
            )

    def test_zero_records_exits_early(self):
        """Test that command exits early when no records found"""
        # Don't create any persons, so count will be 0

        self.command.handle("posthog.Person", team_id=self.team.id)

        # No need to mock task since it should never be called

    def test_batch_size_limit(self):
        """Test that batch size is limited to maximum"""
        with patch("posthog.management.commands.background_delete_model.background_delete_model_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="test-task-id")

            # Create some test persons
            Person.objects.create(team=self.team, properties={})
            Person.objects.create(team=self.team, properties={})

            # Try to use a batch size larger than the limit
            with patch("builtins.input", return_value="DELETE 2 RECORDS"):
                self.command.handle("posthog.Person", team_id=self.team.id, batch_size=100000)

            # Verify task was called with the limited batch size
            mock_task.delay.assert_called_once_with(
                model_name="posthog.Person", team_id=self.team.id, batch_size=50000, records_to_delete=2
            )

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    @patch("builtins.input", return_value="DELETE 2 RECORDS")
    def test_synchronous_execution(self, mock_input, mock_task):
        """Test that synchronous flag runs task directly instead of using .delay()"""
        # Create some test persons
        Person.objects.create(team=self.team, properties={})
        Person.objects.create(team=self.team, properties={})

        self.command.handle("posthog.Person", team_id=self.team.id, synchronous=True)

        # Verify task was called directly (not with .delay())
        mock_task.assert_called_once_with(
            model_name="posthog.Person", team_id=self.team.id, batch_size=10000, records_to_delete=2
        )
        # Verify .delay() was not called
        mock_task.delay.assert_not_called()

    @patch("posthog.management.commands.background_delete_model.background_delete_model_task")
    @patch("builtins.input", return_value="DELETE 2 RECORDS")
    def test_only_deletes_from_specified_team(self, mock_input, mock_task):
        """Test that only records from the specified team are deleted"""
        mock_task.delay.return_value = MagicMock(id="test-task-id")

        # Create a second team
        from posthog.models.team.team import Team

        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Create persons across multiple teams
        Person.objects.create(team=self.team, properties={})  # Team 1
        Person.objects.create(team=self.team, properties={})  # Team 1
        Person.objects.create(team=team2, properties={})  # Team 2
        Person.objects.create(team=team2, properties={})  # Team 2
        Person.objects.create(team=team2, properties={})  # Team 2

        # Verify initial counts
        self.assertEqual(Person.objects.filter(team=self.team).count(), 2)
        self.assertEqual(Person.objects.filter(team=team2).count(), 3)

        # Run command for team 1 only
        self.command.handle("posthog.Person", team_id=self.team.id)

        # Verify task was called with correct team_id
        mock_task.delay.assert_called_once_with(
            model_name="posthog.Person", team_id=self.team.id, batch_size=10000, records_to_delete=2
        )

        # Verify counts haven't changed (since we're just testing the command, not the actual deletion)
        self.assertEqual(Person.objects.filter(team=self.team).count(), 2)
        self.assertEqual(Person.objects.filter(team=team2).count(), 3)

    def test_max_delete_size_limit(self):
        """Test that deletion is limited to max_delete_size when total count exceeds it"""
        # Create a mock model with many records
        with patch("django.apps.apps.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"

            # Mock the _meta.get_fields() to return a field with name 'team_id'
            mock_field = MagicMock()
            mock_field.name = "team_id"
            mock_model._meta.get_fields.return_value = [mock_field]

            # Mock a count that exceeds the default max_delete_size (5M)
            mock_model.objects.filter.return_value.count.return_value = 6000000
            mock_get_model.return_value = mock_model

            # Should not raise error, but should limit deletion to max_delete_size
            with patch("builtins.input", return_value="DELETE 5,000,000 RECORDS"):
                with patch(
                    "posthog.management.commands.background_delete_model.background_delete_model_task"
                ) as mock_task:
                    mock_task.delay.return_value = MagicMock(id="test-task-id")
                    self.command.handle("test.TestModel", team_id=1)

            # Verify task was called (should not be prevented)
            mock_task.delay.assert_called_once_with(
                model_name="test.TestModel", team_id=1, batch_size=10000, records_to_delete=5000000
            )

    def test_max_delete_size_custom_limit(self):
        """Test that custom max_delete_size limit works"""
        with patch("django.apps.apps.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_model.__name__ = "TestModel"

            # Mock the _meta.get_fields() to return a field with name 'team_id'
            mock_field = MagicMock()
            mock_field.name = "team_id"
            mock_model._meta.get_fields.return_value = [mock_field]

            # Mock a count that would exceed default but not custom limit
            mock_model.objects.filter.return_value.count.return_value = 10000000
            mock_get_model.return_value = mock_model

            # Should not raise error with custom max_delete_size
            with patch("builtins.input", return_value="DELETE 10,000,000 RECORDS"):
                with patch(
                    "posthog.management.commands.background_delete_model.background_delete_model_task"
                ) as mock_task:
                    mock_task.delay.return_value = MagicMock(id="test-task-id")
                    self.command.handle("test.TestModel", team_id=1, max_delete_size=15000000)

            # Verify task was called
            mock_task.delay.assert_called_once_with(
                model_name="test.TestModel", team_id=1, batch_size=10000, records_to_delete=10000000
            )
