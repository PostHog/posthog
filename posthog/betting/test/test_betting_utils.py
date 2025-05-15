from unittest.mock import patch
from datetime import timedelta, datetime

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from posthog.models.betting import BetDefinition, ProbabilityDistribution
from posthog.models.team import Team
from posthog.models.user import User
from posthog.betting.betting_utils import create_probability_distribution, generate_bucket_definitions


class TestBettingUtils(TestCase):
    def setUp(self):
        super().setUp()
        from posthog.models.organization import Organization, OrganizationMembership

        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create(email="test@example.com")
        self.team = Team.objects.create(name="Test Team", organization=self.organization)

        OrganizationMembership.objects.create(
            organization=self.organization, user=self.user, level=OrganizationMembership.Level.ADMIN
        )

        self.bet_definition = BetDefinition.objects.create(
            team=self.team,
            title="Test Bet Definition",
            description="This is a test bet definition",
            type=BetDefinition.BetType.PAGEVIEWS,
            bet_parameters={"url": "/test"},
            closing_date=timezone.now() + timedelta(days=7),
            probability_distribution_interval=86400,
        )

    @freeze_time("2023-05-15 12:00:00")
    @patch("posthog.betting.betting_utils.sync_execute")
    def test_create_probability_distribution_success(self, mock_sync_execute):
        # Mock historical data showing a clear trend
        mock_sync_execute.return_value = [
            ("2023-05-07 00:00:00", 100),
            ("2023-05-08 00:00:00", 110),
            ("2023-05-09 00:00:00", 122),
            ("2023-05-10 00:00:00", 131),
            ("2023-05-11 00:00:00", 145),
            ("2023-05-12 00:00:00", 156),
            ("2023-05-13 00:00:00", 170),
            ("2023-05-14 00:00:00", 181),
        ]

        # Set up bet definition with 7 days until closing
        self.bet_definition.closing_date = timezone.now() + timedelta(days=7)
        self.bet_definition.probability_distribution_interval = 86400  # 1 day in seconds
        self.bet_definition.save()

        # Create a probability distribution
        result = create_probability_distribution(self.bet_definition)

        # Verify the result
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ProbabilityDistribution)
        self.assertEqual(result.bet_definition, self.bet_definition)

        # Verify distribution data
        self.assertIsNotNone(result.distribution_data)
        self.assertIsInstance(result.distribution_data, list)

        # Verify each bucket in distribution has required fields and reasonable ranges
        # Based on the trend (roughly +10 per day), in 7 days we expect around 251
        expected_buckets = [
            {"min": 0, "max": 230, "probability": 0.05},  # Low probability of being below trend
            {"min": 231, "max": 246, "probability": 0.15},  # Below trend
            {"min": 247, "max": 253, "probability": 0.60},  # Around trend
            {"min": 254, "max": 270, "probability": 0.15},  # Above trend
            {"min": 271, "max": 1000000, "probability": 0.05},  # High probability of being above trend
        ]

        # Verify we have the expected number of buckets
        self.assertEqual(len(result.distribution_data), len(expected_buckets))

        # Verify each bucket's structure and reasonable probability distribution
        total_probability = 0
        for bucket in result.distribution_data:
            self.assertIn("min", bucket)
            self.assertIn("max", bucket)
            self.assertIn("probability", bucket)
            self.assertGreaterEqual(bucket["probability"], 0)
            self.assertLessEqual(bucket["probability"], 1)
            total_probability += bucket["probability"]

        # Verify probabilities sum to approximately 1
        self.assertAlmostEqual(total_probability, 1.0, places=2)

        # Verify sync_execute was called once for the historical data
        self.assertEqual(mock_sync_execute.call_count, 1)

    @freeze_time("2023-05-15 12:00:00")
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

    @freeze_time("2023-05-15 12:00:00")
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

    @freeze_time("2023-05-15 12:00:00")
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

    @freeze_time("2023-05-15 12:00:00")
    @patch("posthog.betting.betting_utils.sync_execute")
    def test_empty_data_generates_default_buckets(self, mock_sync_execute):
        # Mock the database query to return no results
        mock_sync_execute.return_value = []

        # Create a probability distribution
        result = create_probability_distribution(self.bet_definition)

        # Verify no probability distribution was created when there's no data
        self.assertIsNone(result)
        self.assertEqual(self.bet_definition.probability_distributions.count(), 0)

    @freeze_time("2023-05-15 12:00:00")
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
        with patch("posthog.betting.betting_utils.predict_final_value") as mock_predict:
            # Set up the mock to return a predicted value
            mock_predict.return_value = 250

            _ = create_probability_distribution(self.bet_definition)

            # Verify predict_final_value was called
            calls = mock_predict.call_args_list
            self.assertEqual(len(calls), 1)

            # Get the arguments from the call
            args, kwargs = calls[0]
            intervals, counts, hours_until_closing = args

            # Verify the arguments
            self.assertEqual(len(intervals), 5)  # 5 intervals from mock data
            self.assertEqual(len(counts), 5)  # 5 counts from mock data
            self.assertGreaterEqual(hours_until_closing, 150)  # Should be around 168 hours
            self.assertLessEqual(hours_until_closing, 180)  # Allow some flexibility

    @freeze_time("2023-05-15 12:00:00")
    @patch("posthog.betting.betting_utils.sync_execute")
    def test_probability_distribution_creation_failure(self, mock_sync_execute):
        # Mock the database query to return no results
        mock_sync_execute.return_value = []

        # Create a probability distribution
        result = create_probability_distribution(self.bet_definition)

        # Verify the result is None (failure)
        self.assertIsNone(result)

        # Verify no probability distribution was created
        self.assertEqual(self.bet_definition.probability_distributions.count(), 0)

    @freeze_time("2023-05-15 12:00:00")
    @patch("posthog.betting.betting_utils.sync_execute")
    def test_probability_distribution_creation(self, mock_sync_execute):
        """Test creating a probability distribution for a bet definition."""
        # Create a bet definition
        bet_definition = BetDefinition.objects.create(
            team=self.team,
            title="Test Bet Definition",
            description="This is a test bet definition",
            type=BetDefinition.BetType.PAGEVIEWS,
            bet_parameters={"url": "/test"},
            closing_date=timezone.now() + timedelta(days=7),
        )

        # Mock the database query to return some historical data
        mock_data = [
            (datetime(2025, 5, 1, 0, 0), 100),  # 100 pageviews at start
            (datetime(2025, 5, 2, 0, 0), 150),  # 150 pageviews after 1 day
            (datetime(2025, 5, 3, 0, 0), 200),  # 200 pageviews after 2 days
            (datetime(2025, 5, 4, 0, 0), 250),  # 250 pageviews after 3 days
            (datetime(2025, 5, 5, 0, 0), 300),  # 300 pageviews after 4 days
        ]
        mock_sync_execute.return_value = mock_data

        # Create the probability distribution
        distribution = create_probability_distribution(bet_definition)

        # Verify the distribution was created
        self.assertIsNotNone(distribution)
        self.assertEqual(distribution.bet_definition, bet_definition)

        # Verify the distribution data format
        self.assertIsInstance(distribution.distribution_data, list)
        self.assertEqual(len(distribution.distribution_data), 5)  # 5 buckets

        # Verify each bucket has the correct format
        for bucket in distribution.distribution_data:
            self.assertIn("value", bucket)
            self.assertIn("probability", bucket)
            self.assertIsInstance(bucket["value"], (int, float))
            self.assertIsInstance(bucket["probability"], float)

        # Verify bucket definitions were saved
        bet_definition.refresh_from_db()
        self.assertIsInstance(bet_definition.bucket_definitions, list)
        self.assertEqual(len(bet_definition.bucket_definitions), 5)  # 5 buckets

        # Verify each bucket definition has min and max
        for bucket in bet_definition.bucket_definitions:
            self.assertIn("min", bucket)
            self.assertIn("max", bucket)
            self.assertIsInstance(bucket["min"], (int, float))
            self.assertIsInstance(bucket["max"], (int, float))

        # Verify the total probability is 1
        total_probability = sum(bucket["probability"] for bucket in distribution.distribution_data)
        self.assertAlmostEqual(total_probability, 1.0)

        # Verify the mock was called with the correct parameters
        mock_sync_execute.assert_called_once()
        call_args = mock_sync_execute.call_args_list[0]
        self.assertEqual(call_args[1]["team_id"], self.team.id)
        self.assertEqual(call_args[1]["interval_seconds"], bet_definition.probability_distribution_interval)
        self.assertIn("start_date", call_args[1])
        self.assertIn("end_date", call_args[1])
