"""
Test the activity log helper methods to ensure they work correctly.
"""

from posthog.test.activity_log_helpers import ActivityLogTestHelper


class TestActivityLogHelpers(ActivityLogTestHelper):
    """Test the activity log helper methods."""

    def test_create_cohort(self):
        """Test creating a cohort via API."""
        cohort = self.create_cohort("Test Cohort")
        self.assertEqual(cohort["name"], "Test Cohort")

    def test_update_cohort(self):
        """Test updating a cohort via API."""
        cohort = self.create_cohort("Original Name")
        updated = self.update_cohort(cohort["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_create_feature_flag(self):
        """Test creating a feature flag via API."""
        flag = self.create_feature_flag("test-flag")
        self.assertEqual(flag["key"], "test-flag")

    def test_update_feature_flag(self):
        """Test updating a feature flag via API."""
        flag = self.create_feature_flag("test-flag")
        updated = self.update_feature_flag(flag["id"], {"name": "Updated Flag Name"})
        self.assertEqual(updated["name"], "Updated Flag Name")

    def test_create_insight(self):
        """Test creating an insight via API."""
        insight = self.create_insight("Test Insight")
        self.assertEqual(insight["name"], "Test Insight")

    def test_update_insight(self):
        """Test updating an insight via API."""
        insight = self.create_insight("Original Name")
        updated = self.update_insight(insight["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_create_dashboard(self):
        """Test creating a dashboard via API."""
        dashboard = self.create_dashboard("Test Dashboard")
        self.assertEqual(dashboard["name"], "Test Dashboard")

    def test_update_dashboard(self):
        """Test updating a dashboard via API."""
        dashboard = self.create_dashboard("Original Name")
        updated = self.update_dashboard(dashboard["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_create_notebook(self):
        """Test creating a notebook via API."""
        notebook = self.create_notebook("Test Notebook")
        self.assertEqual(notebook["title"], "Test Notebook")

    def test_update_notebook(self):
        """Test updating a notebook via API."""
        notebook = self.create_notebook("Original Title")
        updated = self.update_notebook(notebook["short_id"], {"title": "Updated Title"})
        self.assertEqual(updated["title"], "Updated Title")

    def test_create_survey(self):
        """Test creating a survey via API."""
        survey = self.create_survey("Test Survey")
        self.assertEqual(survey["name"], "Test Survey")

    def test_update_survey(self):
        """Test updating a survey via API."""
        survey = self.create_survey("Original Name")
        updated = self.update_survey(survey["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_create_experiment(self):
        """Test creating an experiment via API."""
        experiment = self.create_experiment("Test Experiment")
        self.assertEqual(experiment["name"], "Test Experiment")

    def test_update_experiment(self):
        """Test updating an experiment via API."""
        experiment = self.create_experiment("Original Name")
        updated = self.update_experiment(experiment["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")

    def test_create_action(self):
        """Test creating an action via API."""
        action = self.create_action("Test Action")
        self.assertEqual(action["name"], "Test Action")

    def test_update_action(self):
        """Test updating an action via API."""
        action = self.create_action("Original Name")
        updated = self.update_action(action["id"], {"name": "Updated Name"})
        self.assertEqual(updated["name"], "Updated Name")


class TestComprehensiveActivityLogHelpers(ActivityLogTestHelper):
    """Test comprehensive coverage of activity log helper methods."""

    def test_multiple_model_creation_and_updates(self):
        """Test creating and updating multiple model types in sequence."""

        # Create various models
        cohort = self.create_cohort("Test Cohort")
        self.assertIsNotNone(cohort["id"])

        flag = self.create_feature_flag("test-flag")
        self.assertEqual(flag["key"], "test-flag")

        insight = self.create_insight("Test Insight")
        self.assertEqual(insight["name"], "Test Insight")

        dashboard = self.create_dashboard("Test Dashboard")
        self.assertEqual(dashboard["name"], "Test Dashboard")

        notebook = self.create_notebook("Test Notebook")
        self.assertEqual(notebook["title"], "Test Notebook")

        survey = self.create_survey("Test Survey")
        self.assertEqual(survey["name"], "Test Survey")

        action = self.create_action("Test Action")
        self.assertEqual(action["name"], "Test Action")

        # Update the models
        cohort_updated = self.update_cohort(cohort["id"], {"name": "Updated Cohort"})
        self.assertEqual(cohort_updated["name"], "Updated Cohort")

        flag_updated = self.update_feature_flag(flag["id"], {"name": "Updated Flag"})
        self.assertEqual(flag_updated["name"], "Updated Flag")

        insight_updated = self.update_insight(insight["id"], {"name": "Updated Insight"})
        self.assertEqual(insight_updated["name"], "Updated Insight")

        dashboard_updated = self.update_dashboard(dashboard["id"], {"name": "Updated Dashboard"})
        self.assertEqual(dashboard_updated["name"], "Updated Dashboard")

        notebook_updated = self.update_notebook(notebook["short_id"], {"title": "Updated Notebook"})
        self.assertEqual(notebook_updated["title"], "Updated Notebook")

        survey_updated = self.update_survey(survey["id"], {"name": "Updated Survey"})
        self.assertEqual(survey_updated["name"], "Updated Survey")

        action_updated = self.update_action(action["id"], {"name": "Updated Action"})
        self.assertEqual(action_updated["name"], "Updated Action")

    def test_models_with_prerequisites(self):
        """Test models that require other models as prerequisites."""

        # Create a comment (requires an insight)
        self.create_insight("Insight for Comment")
        comment = self.create_comment("Test comment")
        self.assertEqual(comment["content"], "Test comment")

        # Create subscription (requires a dashboard)
        self.create_dashboard("Dashboard for Subscription")
        subscription = self.create_subscription("Test Subscription")
        self.assertEqual(subscription["title"], "Test Subscription")

        # Create alert (requires an insight)
        self.create_insight("Insight for Alert")
        alert = self.create_alert_configuration("Test Alert")
        self.assertEqual(alert["name"], "Test Alert")

    def test_organization_level_models(self):
        """Test organization-level models."""

        # Test personal API key
        api_key = self.create_personal_api_key("Test API Key")
        self.assertEqual(api_key["label"], "Test API Key")

        # Test user updates
        user_update = self.update_user({"first_name": "Updated Name"})
        self.assertEqual(user_update["first_name"], "Updated Name")
