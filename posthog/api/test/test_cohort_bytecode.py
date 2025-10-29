from posthog.test.base import APIBaseTest


class TestCohortBytecode(APIBaseTest):
    """Test bytecode generation functionality for cohort filters"""

    def test_filter_bytecode_generation(self):
        """Test that different filter types generate bytecode correctly"""
        from posthog.api.cohort import BehavioralFilter, CohortFilter, PersonFilter

        # Create a test cohort for CohortFilter
        response = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "Test Cohort", "is_static": True},
        )
        self.assertEqual(response.status_code, 201)
        test_cohort_id = response.json()["id"]

        test_cases = [
            {
                "name": "BehavioralFilter",
                "filter_class": BehavioralFilter,
                "filter_data": {
                    "type": "behavioral",
                    "key": "event_name",
                    "value": "performed_event",
                    "event_type": "events",
                },
            },
            {
                "name": "CohortFilter",
                "filter_class": CohortFilter,
                "filter_data": {"type": "cohort", "key": "id", "value": test_cohort_id},
            },
            {
                "name": "PersonFilter",
                "filter_class": PersonFilter,
                "filter_data": {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
            },
        ]

        for case in test_cases:
            with self.subTest(filter_type=case["name"]):
                filter_instance = case["filter_class"].model_validate(case["filter_data"], context={"team": self.team})

                # Should have valid bytecode and no errors
                self.assertIsNotNone(filter_instance.bytecode, f"{case['name']} should generate bytecode")
                self.assertIsNone(filter_instance.bytecode_error, f"{case['name']} should not have bytecode errors")

                # Should have generated conditionHash
                self.assertIsNotNone(filter_instance.conditionHash, f"{case['name']} should generate conditionHash")
                self.assertIsInstance(filter_instance.conditionHash, str)
                self.assertEqual(len(filter_instance.conditionHash), 16)  # SHA256 truncated to 16 chars

        # Test that identical filters produce the same conditionHash
        filter_data = {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"}
        person_filter1 = PersonFilter.model_validate(filter_data, context={"team": self.team})
        person_filter2 = PersonFilter.model_validate(filter_data, context={"team": self.team})
        self.assertEqual(person_filter1.conditionHash, person_filter2.conditionHash)

    def test_cohort_realtime_support_calculation(self):
        """Test realtime support calculation based on filter types at cohort level"""
        from posthog.models.cohort.cohort import Cohort

        test_cases = [
            {
                "name": "All supported filters",
                "filters": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "behavioral", "key": "purchase", "value": "performed_event", "event_type": "events"},
                ],
                "expected_cohort_type": "realtime",
            },
            {
                "name": "Behavioral with temporal logic",
                "filters": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {
                        "type": "behavioral",
                        "key": "purchase",
                        "value": "performed_event_multiple",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                        "operator_value": 3,
                    },
                ],
                "expected_cohort_type": "realtime",  # Still supported because behavioral filters generate bytecode for event matching
            },
            {
                "name": "Unsupported behavioral filter type",
                "filters": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {
                        "type": "behavioral",
                        "key": "signup",
                        "value": "performed_event_regularly",  # This type doesn't generate bytecode
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                    },
                ],
                "expected_cohort_type": None,  # Should remain None due to unsupported behavioral type
            },
        ]

        for case in test_cases:
            with self.subTest(scenario=case["name"]):
                filters_data = {
                    "properties": {
                        "type": "AND",
                        "values": case["filters"],
                    }
                }

                # Create cohort via API to test realtime support calculation
                response = self.client.post(
                    f"/api/projects/{self.team.id}/cohorts/",
                    {"name": f"Test {case['name']}", "filters": filters_data},
                    format="json",
                )
                self.assertEqual(response.status_code, 201)

                # Get cohort from database and verify cohort_type
                cohort_id = response.json()["id"]
                cohort = Cohort.objects.get(id=cohort_id)
                expected_type = case["expected_cohort_type"]
                if expected_type is None:
                    # Should remain None for unsupported filters
                    self.assertIsNone(cohort.cohort_type)
                else:
                    self.assertEqual(cohort.cohort_type, expected_type)

    def test_cohort_database_persistence(self):
        """Test bytecode persistence and data integrity in database"""
        from posthog.models.cohort.cohort import Cohort

        test_cases = [
            {
                "name": "Simple filters persistence",
                "filters": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "behavioral", "key": "purchase", "value": "performed_event", "event_type": "events"},
                ],
                "expected_bytecode_count": 2,
                "expected_cohort_type": "realtime",
            },
            {
                "name": "Temporal behavioral filter preservation",
                "filters": [
                    {
                        "type": "behavioral",
                        "key": "purchase",
                        "value": "performed_event_multiple",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                        "operator_value": 3,
                        "operator": "gte",
                    }
                ],
                "expected_bytecode_count": 1,
                "expected_cohort_type": "realtime",
                "check_temporal_preservation": True,
            },
        ]

        for case in test_cases:
            with self.subTest(scenario=case["name"]):
                filters_data = {
                    "properties": {
                        "type": "AND",
                        "values": case["filters"],
                    }
                }

                # Create cohort via API
                response = self.client.post(
                    f"/api/projects/{self.team.id}/cohorts/",
                    {"name": f"Test {case['name']}", "filters": filters_data},
                    format="json",
                )
                self.assertEqual(response.status_code, 201)

                # Get cohort from database
                cohort_id = response.json()["id"]
                cohort = Cohort.objects.get(id=cohort_id)

                # Verify cohort type reflects realtime capability
                expected_type = case["expected_cohort_type"]
                if expected_type is None:
                    # Should remain None for unsupported filters
                    self.assertIsNone(cohort.cohort_type)
                else:
                    self.assertEqual(cohort.cohort_type, expected_type)

                # Verify filters are clean (no embedded bytecode)
                filter_values = cohort.filters["properties"]["values"]
                for filter_value in filter_values:
                    self.assertNotIn("bytecode", filter_value)
                    self.assertNotIn("conditionHash", filter_value)

                # Verify compiled_bytecode structure
                self.assertIsNotNone(cohort.compiled_bytecode)
                self.assertIsInstance(cohort.compiled_bytecode, list)
                self.assertEqual(len(cohort.compiled_bytecode), case["expected_bytecode_count"])

                # Verify each bytecode entry structure
                for bytecode_entry in cohort.compiled_bytecode:
                    self.assertIn("filter_path", bytecode_entry)
                    self.assertIn("bytecode", bytecode_entry)
                    self.assertIn("conditionHash", bytecode_entry)
                    self.assertIsInstance(bytecode_entry["bytecode"], list)
                    self.assertGreater(len(bytecode_entry["bytecode"]), 0)
                    self.assertIsInstance(bytecode_entry["conditionHash"], str)
                    self.assertEqual(len(bytecode_entry["conditionHash"]), 16)

                # Special check for temporal parameter preservation
                if case.get("check_temporal_preservation"):
                    stored_filter = filter_values[0]
                    self.assertEqual(stored_filter["time_value"], 30)
                    self.assertEqual(stored_filter["time_interval"], "day")
                    self.assertEqual(stored_filter["operator_value"], 3)
                    self.assertEqual(stored_filter["operator"], "gte")

    def test_complex_cohort_scenarios(self):
        """Test various complex cohort scenarios with different filter combinations"""
        from posthog.models.cohort.cohort import Cohort

        test_cases = [
            {
                "name": "Complex multi-filter cohort",
                "filters": [
                    # Complex behavioral with temporal logic
                    {
                        "type": "behavioral",
                        "key": "purchase_completed",
                        "value": "performed_event_multiple",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                        "operator_value": 3,
                        "operator": "gte",
                    },
                    # Person filter
                    {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"},
                    # Simple behavioral with negation
                    {
                        "type": "behavioral",
                        "key": "churn_event",
                        "value": "performed_event",
                        "event_type": "events",
                        "time_value": 14,
                        "time_interval": "day",
                        "negation": True,
                    },
                    # Person property check
                    {"type": "person", "key": "firstName", "operator": "is_set"},
                ],
                "expected_cohort_type": "realtime",
                "expected_bytecode_count": 4,
                "expected_filter_count": 4,
            },
            {
                "name": "Mixed behavioral types",
                "filters": [
                    # Complex behavioral with temporal logic
                    {
                        "type": "behavioral",
                        "key": "purchase",
                        "value": "performed_event_multiple",
                        "event_type": "events",
                        "time_value": 30,
                        "time_interval": "day",
                        "operator_value": 3,
                        "operator": "gte",
                    },
                    # Simple behavioral
                    {
                        "type": "behavioral",
                        "key": "page_view",
                        "value": "performed_event",
                        "event_type": "events",
                    },
                    # Person filter
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                ],
                "expected_cohort_type": "realtime",
                "expected_bytecode_count": 3,
                "expected_filter_count": 3,
            },
        ]

        for case in test_cases:
            with self.subTest(scenario=case["name"]):
                filters_data = {
                    "properties": {
                        "type": "AND",
                        "values": case["filters"],
                    }
                }

                # Create cohort via API
                response = self.client.post(
                    f"/api/projects/{self.team.id}/cohorts/",
                    {"name": f"Test {case['name']}", "filters": filters_data},
                    format="json",
                )
                self.assertEqual(response.status_code, 201)

                # Get cohort from database
                cohort_id = response.json()["id"]
                cohort = Cohort.objects.get(id=cohort_id)

                # Verify cohort type reflects realtime capability and structure
                expected_type = case["expected_cohort_type"]
                if expected_type is None:
                    # Should remain None for unsupported filters
                    self.assertIsNone(cohort.cohort_type)
                else:
                    self.assertEqual(cohort.cohort_type, expected_type)
                self.assertEqual(len(cohort.filters["properties"]["values"]), case["expected_filter_count"])
                self.assertEqual(len(cohort.compiled_bytecode), case["expected_bytecode_count"])

                # Verify all filters are clean (no embedded bytecode)
                for filter_value in cohort.filters["properties"]["values"]:
                    self.assertNotIn("bytecode", filter_value)
                    self.assertNotIn("conditionHash", filter_value)

                # Verify all bytecode entries have valid structure and expected filter paths
                filter_paths = [entry["filter_path"] for entry in cohort.compiled_bytecode]
                for i in range(case["expected_bytecode_count"]):
                    expected_path = f"properties.values[{i}]"
                    self.assertIn(expected_path, filter_paths, f"Missing bytecode for {expected_path}")

                for bytecode_entry in cohort.compiled_bytecode:
                    self.assertIn("filter_path", bytecode_entry)
                    self.assertIn("bytecode", bytecode_entry)
                    self.assertIn("conditionHash", bytecode_entry)
                    self.assertIsInstance(bytecode_entry["bytecode"], list)
                    self.assertGreater(len(bytecode_entry["bytecode"]), 0)
                    self.assertIsInstance(bytecode_entry["conditionHash"], str)
                    self.assertEqual(len(bytecode_entry["conditionHash"]), 16)
