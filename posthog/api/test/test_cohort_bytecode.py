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

    def test_cohort_filters_realtime_supported_all_valid_bytecode(self):
        """Test that CohortFilters has realtimeSupported=True when all filters have valid bytecode"""
        from posthog.api.cohort import CohortFilters

        filters_data = {
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "realtime", "key": "event_name", "value": "performed_event", "event_type": "events"},
                ],
            }
        }

        cohort_filters = CohortFilters.model_validate(filters_data, context={"team": self.team})

        # Should be realtime supported since all filters can generate bytecode
        self.assertTrue(cohort_filters.realtimeSupported)

    def test_cohort_filters_realtime_not_supported_with_behavioral_filter(self):
        """Test that CohortFilters has realtimeSupported=False when it contains behavioral filters"""
        from posthog.api.cohort import CohortFilters

        filters_data = {
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {
                        "type": "behavioral",
                        "key": "event_name",
                        "value": "performed_event",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                    },
                ],
            }
        }

        cohort_filters = CohortFilters.model_validate(filters_data, context={"team": self.team})

        # Should not be realtime supported since behavioral filters don't generate bytecode
        self.assertFalse(cohort_filters.realtimeSupported)

    def test_cohort_database_persistence_of_bytecode_data(self):
        """Test that bytecode and conditionHash are persisted to database in filters JSON"""

        filters_data = {
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "realtime", "key": "purchase", "value": "performed_event", "event_type": "events"},
                ],
            }
        }

        # Create cohort via API
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "Test Bytecode Persistence", "filters": filters_data},
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        # Get the created cohort from database
        cohort_id = response.json()["id"]
        from posthog.models.cohort.cohort import Cohort

        cohort = Cohort.objects.get(id=cohort_id)

        # Verify realtime_supported flag is set
        self.assertTrue(cohort.realtime_supported)

        # Verify bytecode data is stored in filters JSON
        filters = cohort.filters
        self.assertIsNotNone(filters)

        filter_values = filters["properties"]["values"]

        # Check person filter has bytecode
        person_filter = filter_values[0]
        self.assertIn("bytecode", person_filter)
        self.assertIn("conditionHash", person_filter)
        self.assertIsInstance(person_filter["bytecode"], list)
        self.assertIsInstance(person_filter["conditionHash"], str)
        self.assertEqual(len(person_filter["conditionHash"]), 16)

        # Check realtime filter has bytecode
        realtime_filter = filter_values[1]
        self.assertIn("bytecode", realtime_filter)
        self.assertIn("conditionHash", realtime_filter)
        self.assertIsInstance(realtime_filter["bytecode"], list)
        self.assertIsInstance(realtime_filter["conditionHash"], str)
        self.assertEqual(len(realtime_filter["conditionHash"]), 16)
