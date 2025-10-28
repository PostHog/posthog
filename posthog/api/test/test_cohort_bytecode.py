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

        # Should have generated conditionHash
        self.assertIsNotNone(realtime_filter.conditionHash)
        self.assertIsInstance(realtime_filter.conditionHash, str)
        self.assertEqual(len(realtime_filter.conditionHash), 16)  # SHA256 truncated to 16 chars

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

        # Should have generated conditionHash
        self.assertIsNotNone(cohort_filter.conditionHash)
        self.assertIsInstance(cohort_filter.conditionHash, str)
        self.assertEqual(len(cohort_filter.conditionHash), 16)

    def test_person_filter_bytecode_generation(self):
        """Test that PersonFilter generates bytecode when team context is provided"""
        from posthog.api.cohort import PersonFilter

        filter_data = {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}

        person_filter = PersonFilter.model_validate(filter_data, context={"team": self.team})

        # Should have valid bytecode and no errors for valid filter
        self.assertIsNotNone(person_filter.bytecode)
        self.assertIsNone(person_filter.bytecode_error)

        # Should have generated conditionHash
        self.assertIsNotNone(person_filter.conditionHash)
        self.assertIsInstance(person_filter.conditionHash, str)
        self.assertEqual(len(person_filter.conditionHash), 16)

    def test_identical_filters_same_condition_hash(self):
        """Test that identical filters produce the same conditionHash"""
        from posthog.api.cohort import PersonFilter

        filter_data = {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}

        person_filter1 = PersonFilter.model_validate(filter_data, context={"team": self.team})
        person_filter2 = PersonFilter.model_validate(filter_data, context={"team": self.team})

        # Both filters should have the same conditionHash
        self.assertIsNotNone(person_filter1.conditionHash)
        self.assertIsNotNone(person_filter2.conditionHash)
        self.assertEqual(person_filter1.conditionHash, person_filter2.conditionHash)
