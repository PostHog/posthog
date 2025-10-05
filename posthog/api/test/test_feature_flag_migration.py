import time

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.feature_flag import FeatureFlagSerializer, FeatureFlagViewSet


class TestLaunchDarklyRateLimiter(APIBaseTest):
    """Test the LaunchDarkly rate limiting functionality"""

    def setUp(self):
        super().setUp()
        self.viewset = FeatureFlagViewSet()
        self.serializer = FeatureFlagSerializer()

    def test_rate_limiter_initialization(self):
        """Test rate limiter is properly initialized"""
        rate_limiter = self.viewset.rate_limiter

        # Test that rate limiter exists and has the expected type
        self.assertIsNotNone(rate_limiter)
        self.assertEqual(rate_limiter.__class__.__name__, "LaunchDarklyRateLimiter")

    @patch("requests.get")
    def test_rate_limiter_request_with_backoff(self, mock_get):
        """Test that rate limiter properly handles requests with backoff"""
        rate_limiter = self.viewset.rate_limiter

        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"items": []}
        mock_get.return_value = mock_response

        # Test that a successful request works
        result = rate_limiter.make_request_with_rate_limiting(
            "https://app.launchdarkly.com/api/v2/flags/test", {"Authorization": "test-key"}
        )

        self.assertEqual(result.status_code, 200)
        mock_get.assert_called_once()

    @patch("requests.get")
    @patch("time.sleep")
    def test_rate_limiter_handles_429_with_retry(self, mock_sleep, mock_get):
        """Test that rate limiter properly handles 429 responses with retry"""
        rate_limiter = self.viewset.rate_limiter

        # Mock 429 response first, then success
        responses = [
            Mock(status_code=429, headers={"X-RateLimit-Reset": str(int(time.time()) + 60)}),
            Mock(status_code=200, json=lambda: {"items": []}),
        ]
        mock_get.side_effect = responses

        result = rate_limiter.make_request_with_rate_limiting(
            "https://app.launchdarkly.com/api/v2/flags/test", {"Authorization": "test-key"}
        )

        # Should have made 2 requests (first failed, second succeeded)
        self.assertEqual(mock_get.call_count, 2)
        # Should have slept for backoff
        mock_sleep.assert_called_once()
        # Final result should be success
        self.assertEqual(result.status_code, 200)

    @patch("requests.get")
    def test_rate_limiter_max_retries(self, mock_get):
        """Test that rate limiter respects max retries"""
        rate_limiter = self.viewset.rate_limiter

        # Mock all requests to return 429
        mock_get.return_value = Mock(status_code=429, headers={"X-RateLimit-Reset": str(int(time.time()) + 60)})

        with patch("time.sleep"):  # Speed up test
            result = rate_limiter.make_request_with_rate_limiting(
                "https://app.launchdarkly.com/api/v2/flags/test", {"Authorization": "test-key"}, max_retries=2
            )

        # Should have tried 3 times total (initial + 2 retries)
        self.assertEqual(mock_get.call_count, 3)
        # Final result should still be 429
        self.assertEqual(result.status_code, 429)


class TestSegmentToCohortConversion(APIBaseTest):
    """Test the LaunchDarkly segment to PostHog cohort conversion"""

    def setUp(self):
        super().setUp()
        self.viewset = FeatureFlagViewSet()

    def test_convert_simple_segment_rule(self):
        """Test converting a simple segment rule to cohort filter"""
        clause = {"attribute": "email", "op": "matches", "values": ["posthog\\.com"], "negate": False}

        result = self.viewset._convert_launchdarkly_clause_to_filter(clause)

        expected = {"key": "email", "value": "posthog\\.com", "operator": "regex", "type": "person"}

        self.assertEqual(result, expected)

    @parameterized.expand(
        [
            ("startsWith", "hello", "regex", "^hello"),
            ("endsWith", "world", "regex", "world$"),
            ("contains", "test", "icontains", "test"),
            ("in", "value", "exact", "value"),
            ("lessThan", "100", "lt", "100"),
            ("greaterThan", "50", "gt", "50"),
        ]
    )
    def test_operator_mapping(self, ld_op, value, expected_op, expected_value):
        """Test LaunchDarkly operator mapping to PostHog operators"""
        clause = {"attribute": "custom_attr", "op": ld_op, "values": [value], "negate": False}

        result = self.viewset._convert_launchdarkly_clause_to_filter(clause)

        self.assertEqual(result["operator"], expected_op)
        self.assertEqual(result["value"], expected_value)

    def test_multiple_values_handling(self):
        """Test handling of clauses with multiple values"""
        clause = {"attribute": "country", "op": "in", "values": ["US", "CA", "UK"], "negate": False}

        result = self.viewset._convert_launchdarkly_clause_to_filter(clause)

        self.assertEqual(result["value"], ["US", "CA", "UK"])
        self.assertEqual(result["operator"], "exact")

    def test_empty_segment_rules(self):
        """Test handling of empty segment rules"""
        segment_data = {"rules": []}

        result = self.viewset._convert_segment_to_cohort_filters(segment_data)

        # Should return a filter that never matches
        expected = [{"key": "distinct_id", "value": "NEVER_MATCH_EMPTY_SEGMENT", "operator": "exact", "type": "person"}]

        self.assertEqual(result, expected)

    def test_complex_segment_rules(self):
        """Test converting complex segment with multiple rules and clauses"""
        segment_data = {
            "key": "test-segment",
            "rules": [
                {
                    "clauses": [
                        {"attribute": "email", "op": "matches", "values": ["posthog\\.com"], "negate": False},
                        {"attribute": "country", "op": "in", "values": ["US"], "negate": False},
                    ]
                }
            ],
        }

        result = self.viewset._convert_segment_to_cohort_filters(segment_data)

        self.assertEqual(len(result), 2)

        # Check email filter
        email_filter = next(f for f in result if f["key"] == "email")
        self.assertEqual(email_filter["operator"], "regex")
        self.assertEqual(email_filter["value"], "posthog\\.com")

        # Check country filter
        country_filter = next(f for f in result if f["key"] == "country")
        self.assertEqual(country_filter["operator"], "exact")
        self.assertEqual(country_filter["value"], "US")

    @patch("posthog.models.Cohort.objects.create")
    @patch("posthog.models.Cohort.objects.filter")
    def test_cohort_creation_with_calculation_trigger(self, mock_filter, mock_create):
        """Test that cohort creation triggers calculation"""

        # Mock existing cohort check (return empty queryset)
        mock_filter.return_value = []

        # Mock new cohort creation
        mock_cohort = Mock()
        mock_cohort.id = 123
        mock_create.return_value = mock_cohort

        segment_data = {
            "key": "test-segment",
            "name": "Test Segment",
            "rules": [
                {"clauses": [{"attribute": "email", "op": "matches", "values": ["posthog\\.com"], "negate": False}]}
            ],
        }

        result = self.viewset._find_or_create_cohort_for_segment("test-segment", segment_data, self.team)

        # Verify cohort was created with correct parameters
        mock_create.assert_called_once()
        create_args = mock_create.call_args[1]

        self.assertEqual(create_args["team"], self.team)
        self.assertEqual(create_args["name"], "LaunchDarkly Segment: Test Segment")
        self.assertTrue(create_args["is_calculating"])

        # Verify calculation was triggered
        mock_cohort.calculate_people_ch.assert_called_once_with(pending_version=0)

        self.assertEqual(result, mock_cohort)


class TestLaunchDarklyFlagTransformation(APIBaseTest):
    """Test LaunchDarkly flag transformation logic"""

    def setUp(self):
        super().setUp()
        self.viewset = FeatureFlagViewSet()

    def test_progressive_rollout_detection(self):
        """Test detection of progressive rollout flags"""

        # Flag with progressive rollout in fallthrough
        progressive_flag = {
            "key": "test-flag",
            "environments": {
                "production": {
                    "on": True,
                    "fallthrough": {
                        "rollout": {
                            "experimentAllocation": {"type": "progressiveRollout"},
                            "variations": [{"variation": 0, "weight": 10000}],
                        }
                    },
                }
            },
        }

        self.assertTrue(self.viewset._has_progressive_rollout(progressive_flag, "production"))

        # Flag with progressive rollout in rule
        rule_progressive_flag = {
            "key": "test-flag-2",
            "environments": {
                "production": {
                    "on": True,
                    "rules": [
                        {
                            "rollout": {
                                "experimentAllocation": {"type": "progressiveRollout"},
                                "variations": [{"variation": 0, "weight": 5000}],
                            }
                        }
                    ],
                }
            },
        }

        self.assertTrue(self.viewset._has_progressive_rollout(rule_progressive_flag, "production"))

        # Flag without progressive rollout
        normal_flag = {
            "key": "normal-flag",
            "environments": {
                "production": {
                    "on": True,
                    "fallthrough": {
                        "rollout": {
                            "experimentAllocation": {"type": "normal"},
                            "variations": [{"variation": 0, "weight": 10000}],
                        }
                    },
                }
            },
        }

        self.assertFalse(self.viewset._has_progressive_rollout(normal_flag, "production"))

    def test_segment_rule_based_detection(self):
        """Test detection of rule-based vs list-based segments"""
        # Rule-based segment
        rule_based_segment = {
            "kind": "user",
            "rules": [{"clauses": [{"attribute": "email", "op": "matches", "values": ["posthog\\.com"]}]}],
        }

        self.assertTrue(self.viewset._is_segment_rule_based(rule_based_segment))

        # List-based segment
        list_based_segment = {"kind": "user", "included": ["user1", "user2"], "excluded": ["user3"]}

        self.assertFalse(self.viewset._is_segment_rule_based(list_based_segment))

    def test_boolean_flag_structure(self):
        """Test that boolean flags get correct structure"""
        flag_data = {
            "key": "test-flag",
            "name": "Test Flag",
            "kind": "boolean",
            "environments": {
                "production": {"on": True, "fallthrough": {"variation": 0}, "offVariation": 1, "rules": []}
            },
            "variations": [True, False],
        }

        result = self.viewset._convert_external_flag_to_posthog_format(flag_data, "production", None, None, self.team)

        # Boolean flags should have these specific properties
        self.assertIsNone(result["filters"].get("variant"))
        self.assertEqual(result["filters"].get("payloads"), {})
        self.assertIsNone(result["filters"].get("multivariate"))

    def test_zero_rollout_condition_removal(self):
        """Test that conditions with 0% rollout are removed"""
        flag_data = {
            "key": "test-flag",
            "environments": {
                "production": {
                    "on": True,
                    "fallthrough": {"variation": 1},  # Off variation
                    "offVariation": 1,
                    "rules": [
                        {
                            "variation": 0,  # On variation
                            "clauses": [{"attribute": "email", "op": "matches", "values": ["example.com"]}],
                        }
                    ],
                }
            },
            "variations": [True, False],
        }

        result = self.viewset._convert_external_flag_to_posthog_format(flag_data, "production", None, None, self.team)

        # Should only have the rule condition, not the fallthrough (0% rollout)
        groups = result["filters"]["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rollout_percentage"], 100)

    @parameterized.expand(
        [
            # Multiple percentage rollout rules
            (
                {
                    "rules": [
                        {"rollout": {"variations": [{"variation": 0, "weight": 50000}]}},
                        {"rollout": {"variations": [{"variation": 1, "weight": 30000}]}},
                    ],
                    "fallthrough": {"variation": 0},
                },
                False,
            ),
            # Single rule with direct variation
            ({"rules": [{"variation": 0}], "fallthrough": {"variation": 1}}, True),
            # No rules
            ({"rules": [], "fallthrough": {"variation": 0}}, True),
        ]
    )
    def test_multiple_percentage_rollout_validation(self, targeting, should_be_valid):
        """Test validation of flags with multiple percentage rollout rules"""
        flag_data = {"environments": {"production": {"on": True, "targeting": targeting}}}

        result = self.viewset._is_single_condition_flag(flag_data, "production")
        self.assertEqual(result, should_be_valid)


class TestFeatureFlagMigrationAPI(APIBaseTest):
    """Test the feature flag migration API endpoints"""

    def test_fetch_external_flags_missing_params(self):
        """Test fetch external flags with missing parameters"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/", data={}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and API key are required", response.json()["error"])

    def test_import_flags_missing_params(self):
        """Test import flags with missing parameters"""
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/", data={})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and selected flags are required", response.json()["error"])

    @patch("requests.get")
    def test_fetch_external_flags_success(self, mock_get):
        """Test successful fetch of external flags"""
        # Mock LaunchDarkly API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "key": "test-flag",
                    "name": "Test Flag",
                    "kind": "boolean",
                    "environments": {
                        "production": {
                            "on": True,
                            "targeting": {"rules": [], "fallthrough": {"variation": 0}},
                            "offVariation": 1,
                        }
                    },
                    "variations": [True, False],
                }
            ]
        }
        mock_get.return_value = mock_response

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/",
            data={"provider": "launchdarkly", "api_key": "test-key", "project_key": "test-project"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["total_flags"], 1)
        self.assertEqual(data["importable_count"], 1)
        self.assertEqual(data["non_importable_count"], 0)

        # Check flag structure
        flag = data["importable_flags"][0]
        self.assertEqual(flag["key"], "test-flag")
        self.assertTrue(flag["importable"])

    def test_import_flags_success(self):
        """Test successful import of flags"""
        flag_data = {
            "key": "test-import-flag",
            "name": "Test Import Flag",
            "enabled": True,
            "conditions": [],
            "variants": [],
            "metadata": {"provider": "launchdarkly"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"provider": "launchdarkly", "selected_flags": [flag_data]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 0)

        # Verify flag was created in database
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        created_flag = FeatureFlag.objects.get(key="test-import-flag", team=self.team)
        self.assertEqual(created_flag.name, "Test Import Flag")

    def test_import_flags_duplicate_key_conflict(self):
        """Test import fails when flag key already exists"""
        # Create existing flag
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        FeatureFlag.objects.create(key="existing-flag", team=self.team, created_by=self.user)

        flag_data = {
            "key": "existing-flag",
            "name": "Duplicate Flag",
            "enabled": True,
            "conditions": [],
            "variants": [],
            "metadata": {"provider": "launchdarkly"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"provider": "launchdarkly", "selected_flags": [flag_data]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 1)
        self.assertIn("already exists", data["failed_imports"][0]["error"])
