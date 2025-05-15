from unittest.mock import patch
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from posthog.models.betting import BetDefinition, ProbabilityDistribution
from posthog.models.team import Team
from posthog.models.user import User
from posthog.betting.betting_utils import create_probability_distribution, generate_bucket_definitions


class TestBettingUtils(TestCase):
    def setUp(self):
        super().setUp()
        # Create organization, user, team, and membership for testing
        from posthog.models.organization import Organization, OrganizationMembership

        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create(email="test@example.com")
        self.team = Team.objects.create(name="Test Team", organization=self.organization)

        # Create membership
        OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, level=OrganizationMembership.Level.ADMIN
        )

        # Create a bet definition for testing
        self.bet_definition = BetDefinition.objects.create(
            team=self.team,
            title="Test Bet Definition",
            description="This is a test bet definition",
            type=BetDefinition.BetType.PAGEVIEWS,
            bet_parameters={"url": "/test"},
            closing_date=timezone.now() + timedelta(days=7),
        )

    @patch("posthog.betting.betting_utils.sync_execute")
    def test_create_probability_distribution_success(self, mock_sync_execute):
        # Mock the database query results - now with interval timestamps instead of just dates
        mock_sync_execute.return_value = [
            ("2023-05-01 00:00:00", 100),
            ("2023-05-01 06:00:00", 150),
            ("2023-05-01 12:00:00", 200),
            ("2023-05-01 18:00:00", 120),
            ("2023-05-02 00:00:00", 180),
        ]

        # Clear any existing bucket definitions
        self.bet_definition.bucket_definitions = []
        self.bet_definition.save()

        # Create a probability distribution
        result = create_probability_distribution(self.bet_definition)

        # Verify the result
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ProbabilityDistribution)
        self.assertEqual(result.bet_definition, self.bet_definition)

        # Verify bucket definitions were created
        self.bet_definition.refresh_from_db()
        self.assertGreater(len(self.bet_definition.bucket_definitions), 0)

        # Verify sync_execute was called with the correct parameters
        mock_sync_execute.assert_called_once()

    @patch("posthog.betting.betting_utils.sync_execute")
    def test_bucket_definitions_preserved_on_refresh(self, mock_sync_execute):
        # Mock the database query results with interval timestamps
        mock_sync_execute.return_value = [
            ("2023-05-01 00:00:00", 100),
            ("2023-05-01 06:00:00", 150),
            ("2023-05-01 12:00:00", 200),
            ("2023-05-01 18:00:00", 120),
            ("2023-05-02 00:00:00", 180),
        ]

        # Set initial bucket definitions
        original_bucket_definitions = [
            {"min": 100, "max": 150},
            {"min": 151, "max": 200},
            {"min": 201, "max": 250},
            {"min": 251, "max": 300},
            {"min": 301, "max": 350},
        ]
        self.bet_definition.bucket_definitions = original_bucket_definitions
        self.bet_definition.save()

        # Create a probability distribution (simulating a refresh)
        result = create_probability_distribution(self.bet_definition)

        # Verify the result
        self.assertIsNotNone(result)

        # Verify bucket definitions were preserved
        self.bet_definition.refresh_from_db()
        self.assertEqual(self.bet_definition.bucket_definitions, original_bucket_definitions)

    def test_unsupported_bet_type_raises_error(self):
        # Create a bet definition with an unsupported type
        # We'll temporarily modify the type to simulate an unsupported type
        self.bet_definition.type = "unsupported_type"
        self.bet_definition.save()

        # Attempt to create a probability distribution
        with self.assertRaises(ValueError) as context:
            create_probability_distribution(self.bet_definition)

        # Verify the error message
        self.assertIn("Bet type 'unsupported_type' is not supported", str(context.exception))

        # Reset the bet definition type
        self.bet_definition.type = BetDefinition.BetType.PAGEVIEWS
        self.bet_definition.save()

    @patch("posthog.betting.betting_utils.sync_execute")
    def test_generate_bucket_definitions(self, mock_sync_execute):
        # Test the bucket generation with sample data
        interval_counts = [100, 150, 200, 250, 300, 350, 400]

        # Generate buckets
        buckets = generate_bucket_definitions(interval_counts, num_buckets=5)

        # Verify the buckets
        self.assertEqual(len(buckets), 5)

        # Check that buckets are properly structured
        for bucket in buckets:
            self.assertIn("min", bucket)
            self.assertIn("max", bucket)
            self.assertLessEqual(bucket["min"], bucket["max"])

        # Check that buckets cover the range of data
        self.assertLessEqual(buckets[0]["min"], min(interval_counts))
        self.assertGreaterEqual(buckets[-1]["max"], max(interval_counts))

    @patch("posthog.betting.betting_utils.sync_execute")
    def test_empty_data_generates_default_buckets(self, mock_sync_execute):
        # Mock the database query to return no results
        mock_sync_execute.return_value = []

        # Clear any existing bucket definitions
        self.bet_definition.bucket_definitions = []
        self.bet_definition.save()

        # Create a probability distribution
        create_probability_distribution(self.bet_definition)

        # Verify bucket definitions were created even with no data
        self.bet_definition.refresh_from_db()
        self.assertGreater(len(self.bet_definition.bucket_definitions), 0)

    @patch("posthog.betting.betting_utils.sync_execute")
    def test_prediction_to_closing_date(self, mock_sync_execute):
        # Set closing date to 7 days in the future
        future_closing_date = timezone.now() + timedelta(days=7)
        self.bet_definition.closing_date = future_closing_date
        self.bet_definition.probability_distribution_interval = 3600  # 1 hour interval
        self.bet_definition.save()

        # Mock the database query results with interval timestamps
        mock_sync_execute.return_value = [
            ("2023-05-01 00:00:00", 100),
            ("2023-05-01 01:00:00", 110),
            ("2023-05-01 02:00:00", 120),
            ("2023-05-01 03:00:00", 130),
            ("2023-05-01 04:00:00", 140),
        ]

        # Clear any existing bucket definitions
        self.bet_definition.bucket_definitions = [
            {"min": 100, "max": 150},
            {"min": 151, "max": 200},
            {"min": 201, "max": 250},
        ]
        self.bet_definition.save()

        # Create a probability distribution
        with patch("posthog.betting.betting_utils.predict_future_values") as mock_predict:
            # Set up the mock to verify it's called with the right prediction intervals
            mock_predict.side_effect = (
                lambda intervals, counts, prediction_intervals: counts + [150] * prediction_intervals
            )

            _ = create_probability_distribution(self.bet_definition)

            # Verify predict_future_values was called with approximately the right number of intervals
            # We expect around 7 days * 24 hours = 168 intervals (give or take a few due to time differences)
            calls = mock_predict.call_args_list
            self.assertEqual(len(calls), 1)

            # Get the prediction_intervals argument from the call
            _, _, kwargs = calls[0]
            prediction_intervals = kwargs.get("prediction_intervals", 0)

            # Verify it's in the expected range (should be around 168 hours)
            self.assertGreaterEqual(prediction_intervals, 150)  # Allow some flexibility
            self.assertLessEqual(prediction_intervals, 180)

    @patch("posthog.betting.betting_utils.load_pageview_probability_distribution")
    @patch("posthog.betting.betting_utils.sync_execute")
    def test_probability_distribution_creation_failure(self, mock_sync_execute, mock_load_distribution):
        # Mock the database query results with interval timestamps
        mock_sync_execute.return_value = [
            ("2023-05-01 00:00:00", 100),
            ("2023-05-01 06:00:00", 150),
        ]

        # Mock the distribution loading to return None (failure)
        mock_load_distribution.return_value = None

        # Clear any existing bucket definitions
        self.bet_definition.bucket_definitions = []
        self.bet_definition.save()

        # Create a probability distribution
        result = create_probability_distribution(self.bet_definition)

        # Verify the result is None (failure)
        self.assertIsNone(result)
