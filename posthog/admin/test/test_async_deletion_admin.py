from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.contrib.messages import get_messages

from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.models.team import Team
from posthog.models.organization import Organization
from posthog.admin.admins.async_deletion_admin import CustomEventDeletionForm
from posthog.test.base import BaseTest


class TestCustomEventDeletionForm(TestCase):
    """Test form validation for custom event deletion."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def test_valid_form(self):
        """Test form with valid data."""
        form_data = {"team_id": self.team.id, "predicate": "properties.$geoip_disable = 1", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_missing_team_id(self):
        """Test form validation when team_id is missing."""
        form_data = {"predicate": "properties.$geoip_disable = 1", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("team_id", form.errors)

    def test_invalid_team_id_zero(self):
        """Test form validation with team_id = 0."""
        form_data = {"team_id": 0, "predicate": "properties.$geoip_disable = 1", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("team_id", form.errors)
        self.assertIn("positive integer", str(form.errors["team_id"]))

    def test_invalid_team_id_negative(self):
        """Test form validation with negative team_id."""
        form_data = {"team_id": -5, "predicate": "properties.$geoip_disable = 1", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("team_id", form.errors)

    def test_nonexistent_team_id(self):
        """Test form validation with team that doesn't exist."""
        form_data = {"team_id": 99999, "predicate": "properties.$geoip_disable = 1", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("team_id", form.errors)
        self.assertIn("does not exist", str(form.errors["team_id"]))

    def test_missing_predicate(self):
        """Test form validation when predicate is missing."""
        form_data = {"team_id": self.team.id, "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("predicate", form.errors)

    def test_empty_predicate(self):
        """Test form validation with empty predicate."""
        form_data = {"team_id": self.team.id, "predicate": "   ", "preview_only": True}
        form = CustomEventDeletionForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("predicate", form.errors)

    def test_dangerous_sql_keywords(self):
        """Test form validation blocks dangerous SQL keywords."""
        dangerous_predicates = [
            "DROP TABLE events",
            "CREATE TABLE test",
            "ALTER TABLE events",
            "INSERT INTO events",
            "UPDATE events SET",
            "TRUNCATE TABLE events",
            "DELETE FROM events",
            "properties.test = 1; DROP TABLE events;",
        ]

        for predicate in dangerous_predicates:
            with self.subTest(predicate=predicate):
                form_data = {"team_id": self.team.id, "predicate": predicate, "preview_only": True}
                form = CustomEventDeletionForm(data=form_data)
                self.assertFalse(form.is_valid())
                self.assertIn("predicate", form.errors)
                self.assertIn("cannot contain", str(form.errors["predicate"]))

    def test_safe_predicates(self):
        """Test form allows safe WHERE clause predicates."""
        safe_predicates = [
            "properties.$geoip_disable = 1",
            'event = "test_event"',
            'timestamp > "2023-01-01"',
            'properties.error_type = "timeout"',
            'distinct_id = "user123"',
            "(properties.a = 1 OR properties.b = 2)",
            "properties.nested.value IS NOT NULL",
        ]

        for predicate in safe_predicates:
            with self.subTest(predicate=predicate):
                form_data = {"team_id": self.team.id, "predicate": predicate, "preview_only": True}
                form = CustomEventDeletionForm(data=form_data)
                self.assertTrue(form.is_valid(), f"Form should be valid for predicate: {predicate}")


class TestCustomEventDeletionAdminView(BaseTest):
    """Test Django admin view for custom event deletion."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.url = reverse("admin:posthog_asyncdeletion_custom_deletion")

        # Create staff user
        self.staff_user = User.objects.create_user(
            username="staff_user", email="staff@test.com", password="testpass", is_staff=True
        )

        # Create non-staff user
        self.regular_user = User.objects.create_user(
            username="regular_user", email="user@test.com", password="testpass", is_staff=False
        )

    def test_staff_only_access(self):
        """Test that only staff users can access the custom deletion view."""
        # Test unauthenticated access
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect to login

        # Test non-staff user access
        self.client.login(username="regular_user", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)  # Redirect with error

        # Test staff user access
        self.client.login(username="staff_user", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_get_form_display(self):
        """Test GET request displays the form correctly."""
        self.client.login(username="staff_user", password="testpass")
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Custom Event Deletion")
        self.assertContains(response, "Team ID")
        self.assertContains(response, "SQL WHERE Predicate")
        self.assertContains(response, "Preview Only")
        self.assertContains(response, "Team Scoped")

    @patch("posthog.admin.admins.async_deletion_admin.sync_execute")
    def test_preview_functionality(self, mock_sync_execute):
        """Test preview functionality shows accurate counts and samples."""
        self.client.login(username="staff_user", password="testpass")

        # Mock ClickHouse responses
        mock_sync_execute.side_effect = [
            [[5]],  # Count query result
            [  # Sample query results
                ["uuid1", "test_event", "2023-01-01 10:00:00", "user1", {"prop": "value1"}],
                ["uuid2", "test_event", "2023-01-01 11:00:00", "user2", {"prop": "value2"}],
            ],
        ]

        form_data = {"team_id": self.team.id, "predicate": 'event = "test_event"', "preview_only": True}

        response = self.client.post(self.url, data=form_data)
        self.assertEqual(response.status_code, 200)

        # Check that preview results are displayed
        self.assertContains(response, "Total events matching predicate: 5")
        self.assertContains(response, "Sample Events")
        self.assertContains(response, "uuid1")
        self.assertContains(response, "test_event")

        # Verify ClickHouse queries were called with correct team_id
        self.assertEqual(mock_sync_execute.call_count, 2)
        for call in mock_sync_execute.call_args_list:
            args, kwargs = call
            self.assertIn("team_id", kwargs)
            self.assertEqual(kwargs["team_id"], self.team.id)

    @patch("posthog.admin.admins.async_deletion_admin.sync_execute")
    def test_team_scoped_queries(self, mock_sync_execute):
        """Test that all queries are properly scoped to the specified team."""
        self.client.login(username="staff_user", password="testpass")

        # Create another team to ensure we're not querying it
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        mock_sync_execute.side_effect = [[[3]], []]  # Count and sample results

        form_data = {"team_id": self.team.id, "predicate": "properties.test = 1", "preview_only": True}

        response = self.client.post(self.url, data=form_data)
        self.assertEqual(response.status_code, 200)

        # Verify all queries use the specified team_id
        for call in mock_sync_execute.call_args_list:
            args, kwargs = call
            query = args[0]
            params = kwargs

            # Query should contain team_id filter
            self.assertIn("team_id = %(team_id)s", query)
            self.assertEqual(params["team_id"], self.team.id)
            self.assertNotEqual(params["team_id"], other_team.id)

    @patch("posthog.admin.admins.async_deletion_admin.sync_execute")
    def test_deletion_creation(self, mock_sync_execute):
        """Test that deletions are created correctly when not in preview mode."""
        self.client.login(username="staff_user", password="testpass")

        mock_sync_execute.side_effect = [[[2]], []]  # Count and sample results

        form_data = {
            "team_id": self.team.id,
            "predicate": "properties.delete_me = 1",
            "preview_only": False,  # Actually create deletion
        }

        # Verify no deletions exist initially
        self.assertEqual(AsyncDeletion.objects.filter(deletion_type=DeletionType.Custom).count(), 0)

        response = self.client.post(self.url, data=form_data)
        self.assertEqual(response.status_code, 302)  # Redirect after creation

        # Verify deletion was created
        deletions = AsyncDeletion.objects.filter(deletion_type=DeletionType.Custom)
        self.assertEqual(deletions.count(), 1)

        deletion = deletions.first()
        self.assertEqual(deletion.team_id, self.team.id)
        self.assertEqual(deletion.key, "properties.delete_me = 1")
        self.assertEqual(deletion.created_by, self.staff_user)

    def test_form_validation_errors_displayed(self):
        """Test that form validation errors are properly displayed."""
        self.client.login(username="staff_user", password="testpass")

        # Submit form with invalid data
        form_data = {
            "team_id": 99999,  # Non-existent team
            "predicate": "DROP TABLE events",  # Dangerous SQL
            "preview_only": True,
        }

        response = self.client.post(self.url, data=form_data)
        self.assertEqual(response.status_code, 200)

        # Check that errors are displayed
        self.assertContains(response, "does not exist")
        self.assertContains(response, "cannot contain")

    @patch("posthog.admin.admins.async_deletion_admin.sync_execute")
    def test_clickhouse_error_handling(self, mock_sync_execute):
        """Test error handling when ClickHouse queries fail."""
        self.client.login(username="staff_user", password="testpass")

        # Mock ClickHouse error
        mock_sync_execute.side_effect = Exception("ClickHouse connection error")

        form_data = {"team_id": self.team.id, "predicate": "properties.test = 1", "preview_only": True}

        response = self.client.post(self.url, data=form_data)
        self.assertEqual(response.status_code, 200)

        # Check that error message is displayed
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("Error executing query" in str(m) for m in messages))

    def test_success_message_team_scoping(self):
        """Test that success messages emphasize team scoping."""
        self.client.login(username="staff_user", password="testpass")

        with patch("posthog.admin.admins.async_deletion_admin.sync_execute") as mock_sync_execute:
            mock_sync_execute.side_effect = [[[1]], []]

            form_data = {"team_id": self.team.id, "predicate": "properties.test = 1", "preview_only": False}

            response = self.client.post(self.url, data=form_data, follow=True)

            # Check success message mentions team scoping
            messages = list(get_messages(response.wsgi_request))
            success_messages = [str(m) for m in messages if m.tags == "success"]
            self.assertTrue(len(success_messages) > 0)

            success_msg = success_messages[0]
            self.assertIn(f"team {self.team.id}", success_msg)
            self.assertIn("scoped only to team", success_msg)

    def test_zero_events_handling(self):
        """Test handling when no events match the predicate."""
        self.client.login(username="staff_user", password="testpass")

        with patch("posthog.admin.admins.async_deletion_admin.sync_execute") as mock_sync_execute:
            mock_sync_execute.side_effect = [[[0]], []]  # No events found

            form_data = {"team_id": self.team.id, "predicate": "properties.nonexistent = 1", "preview_only": True}

            response = self.client.post(self.url, data=form_data)
            self.assertEqual(response.status_code, 200)

            # Should show "no events found" message
            self.assertContains(response, "No events found matching this predicate")
