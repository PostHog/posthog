from typing import Any, cast

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

        test_cases: list[dict[str, Any]] = [
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
                filter_instance = cast(Any, case["filter_class"]).model_validate(
                    case["filter_data"], context={"team": self.team}
                )

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

        test_cases: list[dict[str, Any]] = [
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
                # Trigger computation of cohort_type by PATCHing filters (create no longer sets type)
                self.client.patch(
                    f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
                    {"filters": filters_data},
                    format="json",
                )
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

        test_cases: list[dict[str, Any]] = [
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
                # Trigger computation of cohort_type by PATCHing filters (create no longer sets type)
                self.client.patch(
                    f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
                    {"filters": filters_data},
                    format="json",
                )
                cohort = Cohort.objects.get(id=cohort_id)

                # Verify cohort type reflects realtime capability
                expected_type = case["expected_cohort_type"]
                if expected_type is None:
                    # Should remain None for unsupported filters
                    self.assertIsNone(cohort.cohort_type)
                else:
                    self.assertEqual(cohort.cohort_type, expected_type)

                # Verify filters are clean (no embedded bytecode)
                filters_dict = cast(dict[str, Any], cohort.filters)
                filter_values = cast(list[dict[str, Any]], filters_dict["properties"]["values"])
                for filter_value in filter_values:
                    self.assertNotIn("bytecode", filter_value)
                    self.assertNotIn("conditionHash", filter_value)

                # Verify compiled_bytecode structure
                self.assertIsNotNone(cohort.compiled_bytecode)
                compiled = cast(list[dict[str, Any]], cohort.compiled_bytecode)
                self.assertIsInstance(compiled, list)
                self.assertEqual(len(compiled), cast(int, case["expected_bytecode_count"]))

                # Verify each bytecode entry structure
                for bytecode_entry in compiled:
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

        test_cases: list[dict[str, Any]] = [
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
                # Trigger computation of cohort_type by PATCHing filters (create no longer sets type)
                self.client.patch(
                    f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
                    {"filters": filters_data},
                    format="json",
                )
                cohort = Cohort.objects.get(id=cohort_id)

                # Verify cohort type reflects realtime capability and structure
                expected_type = case["expected_cohort_type"]
                if expected_type is None:
                    # Should remain None for unsupported filters
                    self.assertIsNone(cohort.cohort_type)
                else:
                    self.assertEqual(cohort.cohort_type, expected_type)
                filters_dict2 = cast(dict[str, Any], cohort.filters)
                self.assertEqual(
                    len(cast(list[Any], filters_dict2["properties"]["values"])),
                    cast(int, case["expected_filter_count"]),
                )
                compiled2 = cast(list[dict[str, Any]], cohort.compiled_bytecode)
                self.assertEqual(len(compiled2), cast(int, case["expected_bytecode_count"]))

                # Verify all filters are clean (no embedded bytecode)
                for filter_value in cast(list[dict[str, Any]], filters_dict2["properties"]["values"]):
                    self.assertNotIn("bytecode", filter_value)
                    self.assertNotIn("conditionHash", filter_value)

                # Verify all bytecode entries have valid structure and expected filter paths
                filter_paths = [entry["filter_path"] for entry in compiled2]
                for i in range(cast(int, case["expected_bytecode_count"])):
                    expected_path = f"properties.values[{i}]"
                    self.assertIn(expected_path, filter_paths, f"Missing bytecode for {expected_path}")

                for bytecode_entry in compiled2:
                    self.assertIn("filter_path", bytecode_entry)
                    self.assertIn("bytecode", bytecode_entry)
                    self.assertIn("conditionHash", bytecode_entry)
                    self.assertIsInstance(bytecode_entry["bytecode"], list)
                    self.assertGreater(len(bytecode_entry["bytecode"]), 0)
                    self.assertIsInstance(bytecode_entry["conditionHash"], str)
                    self.assertEqual(len(bytecode_entry["conditionHash"]), 16)

    def test_update_with_changed_filters_recalculates_bytecode_and_type(self):
        """Updating filters should re-derive compiled_bytecode and cohort_type accordingly"""
        from posthog.models.cohort.cohort import Cohort

        # Start with realtime-capable filters (person + simple behavioral)
        base_filters = {
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "behavioral", "key": "purchase", "value": "performed_event", "event_type": "events"},
                ],
            }
        }

        create_resp = self.client.post(
            f"/api/projects/{self.team.id}/cohorts/",
            {"name": "Update Recalc", "filters": base_filters},
            format="json",
        )
        self.assertEqual(create_resp.status_code, 201)
        cohort_id = create_resp.json()["id"]
        cohort = Cohort.objects.get(id=cohort_id)
        # cohort_type is computed on create when filters support realtime
        self.assertEqual(cohort.cohort_type, "realtime")
        self.assertIsNotNone(cohort.compiled_bytecode)
        base_len = len(cast(list[dict[str, Any]], cohort.compiled_bytecode))

        # Case A: make filters unsupported by adding an unsupported behavioral value
        unsupported_filters = {
            "properties": {
                "type": "AND",
                "values": [
                    *base_filters["properties"]["values"],
                    {
                        "type": "behavioral",
                        "key": "signup",
                        "value": "performed_event_regularly",  # unsupported
                        "event_type": "events",
                    },
                ],
            }
        }

        update_resp = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
            {"filters": unsupported_filters},
            format="json",
        )
        self.assertEqual(update_resp.status_code, 200)
        cohort.refresh_from_db()
        self.assertIsNone(cohort.cohort_type)
        # bytecode still generated for supported filters; length should be >= base_len
        self.assertIsNotNone(cohort.compiled_bytecode)
        self.assertGreaterEqual(len(cast(list[dict[str, Any]], cohort.compiled_bytecode)), base_len)

        # Case B: switch back to supported by replacing the unsupported with supported behavioral
        supported_filters = {
            "properties": {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                    {"type": "behavioral", "key": "purchase", "value": "performed_event", "event_type": "events"},
                    {"type": "behavioral", "key": "page_view", "value": "performed_event", "event_type": "events"},
                ],
            }
        }

        update_resp2 = self.client.patch(
            f"/api/projects/{self.team.id}/cohorts/{cohort_id}/",
            {"filters": supported_filters},
            format="json",
        )
        self.assertEqual(update_resp2.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, "realtime")
        self.assertIsNotNone(cohort.compiled_bytecode)
        self.assertEqual(len(cast(list[dict[str, Any]], cohort.compiled_bytecode)), 3)

    def test_behavioral_bytecode_supported_and_unsupported_generation(self):
        """
        Checks that performed_event_multiple and performed_event_first_time downgrade to performed_event matcher with correct explicit_datetime,
        and unsupported behavioral types are not compiled for bytecode.
        """
        from posthog.models.cohort.cohort import Cohort

        # Supported case: performed_event_multiple
        cohort_data_supported = {
            "name": "test behavioral bytecode supported",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_multiple",
                            "event_type": "events",
                            "time_value": 30,
                            "time_interval": "day",
                        }
                    ],
                }
            },
        }
        resp_ok = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data_supported, format="json")
        self.assertEqual(resp_ok.status_code, 201)
        cohort_id_ok = resp_ok.json()["id"]
        # PATCH to trigger cohort_type logic
        self.client.patch(f"/api/projects/{self.team.id}/cohorts/{cohort_id_ok}/", cohort_data_supported, format="json")
        cohort_ok = Cohort.objects.get(id=cohort_id_ok)
        self.assertEqual(cohort_ok.cohort_type, "realtime")
        self.assertIsInstance(cohort_ok.compiled_bytecode, list)
        self.assertEqual(len(cohort_ok.compiled_bytecode), 1)
        # Bytecode contains only performed_event matcher (downgraded), not performed_event_multiple, and the filter JSON stays as originally input
        bytecode_entry = cohort_ok.compiled_bytecode[0]
        self.assertNotIn("performed_event_multiple", str(bytecode_entry["bytecode"]))
        self.assertIn("performed_event", str(bytecode_entry["bytecode"]))
        filters_dict = cohort_ok.filters
        filter_val = filters_dict["properties"]["values"][0]
        self.assertEqual(filter_val["value"], "performed_event_multiple")

        # Unsupported cases: performed_event_first_time and performed_event_regularly
        for unsupported_val in ["performed_event_first_time", "performed_event_regularly"]:
            cohort_data_unsupported = {
                "name": f"test behavioral bytecode unsupported {unsupported_val}",
                "filters": {
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "behavioral",
                                "key": "$pageview",
                                "value": unsupported_val,
                                "event_type": "events",
                                "time_value": 7,
                                "time_interval": "week",
                            }
                        ],
                    }
                },
            }
            resp_no = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data_unsupported, format="json")
            self.assertEqual(resp_no.status_code, 201)
            cohort_id_no = resp_no.json()["id"]
            self.client.patch(
                f"/api/projects/{self.team.id}/cohorts/{cohort_id_no}/", cohort_data_unsupported, format="json"
            )
            cohort_no = Cohort.objects.get(id=cohort_id_no)
            # Should NOT be considered realtime
            self.assertIsNone(cohort_no.cohort_type)
            # Should NOT emit any relevant bytecode
            self.assertTrue(cohort_no.compiled_bytecode is None or not cohort_no.compiled_bytecode)


class TestCohortTypePersistence(TestCohortBytecode):
    def test_cohort_type_set_on_create_supported(self):
        cohort_data = {
            "name": "test cohort_type on create supported",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_multiple",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data, format="json")
        self.assertEqual(resp.status_code, 201)
        cohort_id = resp.json()["id"]
        from posthog.models.cohort.cohort import Cohort

        cohort = Cohort.objects.get(id=cohort_id)
        self.assertEqual(cohort.cohort_type, "realtime")
        self.assertIsInstance(cohort.compiled_bytecode, list)

    def test_cohort_type_set_on_create_unsupported(self):
        cohort_data = {
            "name": "test cohort_type on create unsupported",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data, format="json")
        self.assertEqual(resp.status_code, 201)
        cohort_id = resp.json()["id"]
        from posthog.models.cohort.cohort import Cohort

        cohort = Cohort.objects.get(id=cohort_id)
        self.assertIsNone(cohort.cohort_type)
        self.assertTrue(cohort.compiled_bytecode is None or not cohort.compiled_bytecode)

    def test_cohort_type_flips_on_update(self):
        from posthog.models.cohort.cohort import Cohort

        # Create unsupported
        cohort_data = {
            "name": "test cohort_type on update flip",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data, format="json")
        self.assertEqual(resp.status_code, 201)
        cohort_id = resp.json()["id"]
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertIsNone(cohort.cohort_type)
        # Patch to supported
        patch_data = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_multiple",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.patch(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/", patch_data, format="json")
        self.assertEqual(resp.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, "realtime")
        # Flip back to unsupported
        patch_data2 = {
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.patch(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/", patch_data2, format="json")
        self.assertEqual(resp.status_code, 200)
        cohort.refresh_from_db()
        self.assertIsNone(cohort.cohort_type)

    def test_explicit_cohort_type_field_preserved_on_patch(self):
        from posthog.models.cohort.cohort import Cohort

        # Supported on create
        cohort_data = {
            "name": "test cohort_type explicit field",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event_multiple",
                            "event_type": "events",
                        }
                    ],
                }
            },
        }
        resp = self.client.post(f"/api/projects/{self.team.id}/cohorts/", cohort_data, format="json")
        self.assertEqual(resp.status_code, 201)
        cohort_id = resp.json()["id"]
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertEqual(cohort.cohort_type, "realtime")
        # Patch explicit value should be ignored (read-only), response OK and value unchanged
        patch_data = {"cohort_type": "static"}
        resp = self.client.patch(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/", patch_data, format="json")
        self.assertEqual(resp.status_code, 200)
        cohort.refresh_from_db()
        self.assertEqual(cohort.cohort_type, "realtime")
