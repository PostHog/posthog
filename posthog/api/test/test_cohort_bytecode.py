from posthog.test.base import APIBaseTest


class TestCohortBytecode(APIBaseTest):
    """Test bytecode generation functionality for cohort filters"""

    def test_realtime_filter_bytecode_generation(self):
        """Test that RealtimeFilter generates bytecode when team context is provided"""
        from posthog.api.cohort import RealtimeFilter

        filter_data = {"type": "realtime", "key": "event_name", "value": "performed_event", "event_type": "events"}

        realtime_filter = RealtimeFilter.model_validate(filter_data, context={"team": self.team})

        # Should have valid bytecode and no errors for valid realtime filter
        self.assertIsNotNone(realtime_filter.bytecode)
        self.assertIsNone(realtime_filter.bytecode_error)

    def test_cohort_filter_bytecode_generation(self):
        """Test that CohortFilter generates bytecode when team context is provided"""
        from posthog.api.cohort import CohortFilter

        # Create a cohort to reference via API
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "Test Cohort", "is_static": True},
        )
        self.assertEqual(response.status_code, 201)
        test_cohort_id = response.json()["id"]

        filter_data = {"type": "cohort", "key": "id", "value": test_cohort_id}

        cohort_filter = CohortFilter.model_validate(filter_data, context={"team": self.team})

        # Should have valid bytecode and no errors for valid filter
        self.assertIsNotNone(cohort_filter.bytecode)
        self.assertIsNone(cohort_filter.bytecode_error)

    def test_person_filter_bytecode_generation(self):
        """Test that PersonFilter generates bytecode when team context is provided"""
        from posthog.api.cohort import PersonFilter

        filter_data = {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}

        person_filter = PersonFilter.model_validate(filter_data, context={"team": self.team})

        # Should have valid bytecode and no errors for valid filter
        self.assertIsNotNone(person_filter.bytecode)
        self.assertIsNone(person_filter.bytecode_error)
