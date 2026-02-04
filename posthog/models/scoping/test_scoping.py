"""
Tests for the team scoping proof-of-concept.

Run with: pytest posthog/models/scoping/test_scoping.py -v
"""

from django.test import TestCase

from posthog.models import FeatureFlag, Organization, Team, User
from posthog.models.scoping import get_current_team_id, team_scope, unscoped


class TestTeamScopingContext(TestCase):
    """Test the context management functions."""

    def test_get_current_team_id_returns_none_by_default(self):
        """Without any context set, get_current_team_id returns None."""
        self.assertIsNone(get_current_team_id())

    def test_team_scope_context_manager_sets_team_id(self):
        """team_scope() context manager sets the current team_id."""
        self.assertIsNone(get_current_team_id())

        with team_scope(123):
            self.assertEqual(get_current_team_id(), 123)

        # After exiting, it should be None again
        self.assertIsNone(get_current_team_id())

    def test_team_scope_can_be_nested(self):
        """Nested team_scope() contexts work correctly."""
        self.assertIsNone(get_current_team_id())

        with team_scope(100):
            self.assertEqual(get_current_team_id(), 100)

            with team_scope(200):
                self.assertEqual(get_current_team_id(), 200)

            # Back to outer scope
            self.assertEqual(get_current_team_id(), 100)

        self.assertIsNone(get_current_team_id())

    def test_unscoped_context_manager_clears_team_id(self):
        """unscoped() context manager temporarily clears the team_id."""
        with team_scope(123):
            self.assertEqual(get_current_team_id(), 123)

            with unscoped():
                self.assertIsNone(get_current_team_id())

            # Back to scoped
            self.assertEqual(get_current_team_id(), 123)


class TestTeamScopedQuerySet(TestCase):
    """Test the TeamScopedQuerySet behavior."""

    @classmethod
    def setUpTestData(cls):
        """Create test data for all tests."""
        cls.organization = Organization.objects.create(name="Test Org")
        cls.user = User.objects.create(email="test@posthog.com")

        cls.team1 = Team.objects.create(
            organization=cls.organization,
            name="Team 1",
            api_token="token_team1",
        )
        cls.team2 = Team.objects.create(
            organization=cls.organization,
            name="Team 2",
            api_token="token_team2",
        )

        # Create feature flags for each team
        cls.flag1_team1 = FeatureFlag.objects.create(
            team=cls.team1,
            key="flag-team1-a",
            name="Flag A for Team 1",
            created_by=cls.user,
        )
        cls.flag2_team1 = FeatureFlag.objects.create(
            team=cls.team1,
            key="flag-team1-b",
            name="Flag B for Team 1",
            created_by=cls.user,
        )
        cls.flag1_team2 = FeatureFlag.objects.create(
            team=cls.team2,
            key="flag-team2-a",
            name="Flag A for Team 2",
            created_by=cls.user,
        )

    def test_without_scope_returns_all(self):
        """Without team scope, queries return all records (current behavior)."""
        # FeatureFlag currently uses RootTeamManager, not TeamScopedManager
        # This test verifies current behavior
        flags = FeatureFlag.objects.filter(key__startswith="flag-team")
        self.assertEqual(flags.count(), 3)

    def test_manual_team_scope_filters_correctly(self):
        """
        Demonstrate how team_scope would work if we switched to TeamScopedManager.

        This test manually applies the filter to simulate what would happen
        with automatic scoping.
        """
        with team_scope(self.team1.id):
            # Simulate what TeamScopedManager would do
            team_id = get_current_team_id()
            self.assertEqual(team_id, self.team1.id)

            # Manual filter (what the manager would do automatically)
            flags = FeatureFlag.objects.filter(team_id=team_id, key__startswith="flag-team")
            self.assertEqual(flags.count(), 2)
            self.assertEqual({f.key for f in flags}, {"flag-team1-a", "flag-team1-b"})

        with team_scope(self.team2.id):
            team_id = get_current_team_id()
            flags = FeatureFlag.objects.filter(team_id=team_id, key__startswith="flag-team")
            self.assertEqual(flags.count(), 1)
            self.assertEqual(flags.first().key, "flag-team2-a")


class TestBackwardsCompatibility(TestCase):
    """Test that the new manager maintains backwards compatibility."""

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Backwards Compat Org")
        cls.user = User.objects.create(email="compat@posthog.com")
        cls.team = Team.objects.create(
            organization=cls.organization,
            name="Compat Team",
            api_token="token_compat",
        )
        cls.flag = FeatureFlag.objects.create(
            team=cls.team,
            key="compat-flag",
            name="Compatibility Flag",
            created_by=cls.user,
        )

    def test_explicit_team_id_filter_still_works(self):
        """Existing code using filter(team_id=X) should continue to work."""
        # This is the current pattern used throughout PostHog
        flags = FeatureFlag.objects.filter(team_id=self.team.id)
        self.assertEqual(flags.count(), 1)
        self.assertEqual(flags.first().key, "compat-flag")

    def test_get_with_pk_still_works(self):
        """Existing code using .get(pk=X) should continue to work."""
        flag = FeatureFlag.objects.get(pk=self.flag.id)
        self.assertEqual(flag.key, "compat-flag")


class TestIDORProtection(TestCase):
    """
    Test that demonstrates how automatic scoping prevents IDOR vulnerabilities.
    """

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="IDOR Test Org")
        cls.user = User.objects.create(email="idor@posthog.com")

        cls.team_victim = Team.objects.create(
            organization=cls.organization,
            name="Victim Team",
            api_token="token_victim",
        )
        cls.team_attacker = Team.objects.create(
            organization=cls.organization,
            name="Attacker Team",
            api_token="token_attacker",
        )

        # Victim's sensitive flag
        cls.victim_flag = FeatureFlag.objects.create(
            team=cls.team_victim,
            key="secret-feature",
            name="Victim's Secret Feature",
            created_by=cls.user,
        )

    def test_idor_vulnerability_without_scoping(self):
        """
        WITHOUT automatic scoping, an attacker can access victim's flag by ID.

        This demonstrates the current vulnerability that semgrep rules try to catch.
        """
        # Attacker knows the victim's flag ID (e.g., from URL enumeration)
        victim_flag_id = self.victim_flag.id

        # Current vulnerable pattern - no team scoping!
        flag = FeatureFlag.objects.get(pk=victim_flag_id)

        # Attacker successfully retrieved victim's flag
        self.assertEqual(flag.key, "secret-feature")
        self.assertEqual(flag.team_id, self.team_victim.id)

    def test_idor_protected_with_manual_scoping(self):
        """
        WITH manual team scoping (current best practice), IDOR is prevented.
        """
        victim_flag_id = self.victim_flag.id

        # Attacker's context
        with team_scope(self.team_attacker.id):
            # Safe pattern - includes team filter
            flag = FeatureFlag.objects.filter(team_id=get_current_team_id()).filter(pk=victim_flag_id).first()

            # Attack failed - flag not found
            self.assertIsNone(flag)

    def test_idor_protected_with_automatic_scoping_concept(self):
        """
        Demonstrates how automatic scoping WOULD work.

        With TeamScopedManager, the team filter would be applied automatically,
        making it impossible to accidentally forget the team check.
        """
        victim_flag_id = self.victim_flag.id

        with team_scope(self.team_attacker.id):
            # With automatic scoping, this would be safe:
            # flag = FeatureFlag.objects.get(pk=victim_flag_id)
            #
            # The manager would automatically add the team filter,
            # resulting in: FeatureFlag.objects.filter(team_id=attacker_team).get(pk=X)
            # Which would raise DoesNotExist

            # Simulating automatic scoping:
            team_id = get_current_team_id()
            with self.assertRaises(FeatureFlag.DoesNotExist):
                FeatureFlag.objects.filter(team_id=team_id).get(pk=victim_flag_id)
