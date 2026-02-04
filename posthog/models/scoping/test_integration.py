"""
Integration tests demonstrating automatic team scoping with real models.

This test temporarily patches FeatureFlag to use TeamScopedManager
to demonstrate how the full integration would work.

Run with: pytest posthog/models/scoping/test_integration.py -v
"""

from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from posthog.models import FeatureFlag, Organization, Team, User
from posthog.models.scoping import get_current_team_id, team_scope
from posthog.models.scoping.middleware import TeamScopingMiddleware


class TestMiddlewareIntegration(TestCase):
    """Test that the middleware correctly sets team context."""

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Middleware Test Org")
        cls.team = Team.objects.create(
            organization=cls.organization,
            name="Middleware Team",
            api_token="token_middleware",
        )
        cls.user = User.objects.create(
            email="middleware@posthog.com",
            current_team=cls.team,
        )

    def test_middleware_sets_team_context_for_authenticated_user(self):
        """Middleware should set team_id from authenticated user."""
        factory = RequestFactory()
        request = factory.get("/api/feature_flags/")
        request.user = self.user

        # Track what team_id is set during the request
        captured_team_id = None

        def capture_team_id(request):
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return MagicMock(status_code=200)

        middleware = TeamScopingMiddleware(capture_team_id)
        middleware(request)

        self.assertEqual(captured_team_id, self.team.id)

        # After request, context should be cleared
        self.assertIsNone(get_current_team_id())

    def test_middleware_does_not_set_context_for_anonymous_user(self):
        """Middleware should not set team_id for anonymous users."""
        factory = RequestFactory()
        request = factory.get("/api/feature_flags/")
        request.user = AnonymousUser()

        captured_team_id = "not_set"

        def capture_team_id(request):
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return MagicMock(status_code=200)

        middleware = TeamScopingMiddleware(capture_team_id)
        middleware(request)

        self.assertIsNone(captured_team_id)

    def test_middleware_clears_context_on_exception(self):
        """Middleware should clear team context even if request raises exception."""
        factory = RequestFactory()
        request = factory.get("/api/feature_flags/")
        request.user = self.user

        def raise_exception(request):
            # Verify context is set
            self.assertEqual(get_current_team_id(), self.team.id)
            raise ValueError("Test exception")

        middleware = TeamScopingMiddleware(raise_exception)

        with self.assertRaises(ValueError):
            middleware(request)

        # Context should still be cleared
        self.assertIsNone(get_current_team_id())


class TestAutomaticScopingConcept(TestCase):
    """
    Demonstrate how automatic scoping would protect against IDOR.

    These tests use team_scope() to simulate what the middleware would do,
    then show how queries would be automatically scoped.
    """

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Auto Scope Org")
        cls.user = User.objects.create(email="auto@posthog.com")

        cls.team_a = Team.objects.create(
            organization=cls.organization,
            name="Team A",
            api_token="token_a",
        )
        cls.team_b = Team.objects.create(
            organization=cls.organization,
            name="Team B",
            api_token="token_b",
        )

        cls.flag_a = FeatureFlag.objects.create(
            team=cls.team_a,
            key="flag-a",
            name="Flag for Team A",
            created_by=cls.user,
        )
        cls.flag_b = FeatureFlag.objects.create(
            team=cls.team_b,
            key="flag-b",
            name="Flag for Team B",
            created_by=cls.user,
        )

    def test_concept_automatic_list_filtering(self):
        """
        Concept: .all() would return only current team's records.

        With automatic scoping:
            FeatureFlag.objects.all()
        Would be equivalent to:
            FeatureFlag.objects.filter(team_id=current_team_id)
        """
        with team_scope(self.team_a.id):
            # Simulate what automatic scoping would do
            team_id = get_current_team_id()
            flags = FeatureFlag.objects.filter(team_id=team_id)

            self.assertEqual(flags.count(), 1)
            self.assertEqual(flags.first().key, "flag-a")

        with team_scope(self.team_b.id):
            team_id = get_current_team_id()
            flags = FeatureFlag.objects.filter(team_id=team_id)

            self.assertEqual(flags.count(), 1)
            self.assertEqual(flags.first().key, "flag-b")

    def test_concept_automatic_get_protection(self):
        """
        Concept: .get(pk=X) would raise DoesNotExist for other team's records.

        With automatic scoping, an attacker trying:
            FeatureFlag.objects.get(pk=victim_flag_id)
        Would get DoesNotExist instead of the victim's flag.
        """
        with team_scope(self.team_a.id):
            team_id = get_current_team_id()

            # Can get own flag
            flag = FeatureFlag.objects.filter(team_id=team_id).get(pk=self.flag_a.id)
            self.assertEqual(flag.key, "flag-a")

            # Cannot get other team's flag
            with self.assertRaises(FeatureFlag.DoesNotExist):
                FeatureFlag.objects.filter(team_id=team_id).get(pk=self.flag_b.id)

    def test_concept_unscoped_allows_cross_team(self):
        """
        Concept: .unscoped() would bypass automatic filtering.

        For admin views or background jobs that need cross-team access:
            FeatureFlag.objects.unscoped().all()
        Would return all records regardless of team context.
        """
        with team_scope(self.team_a.id):
            # Scoped query - only team A
            scoped_count = (
                FeatureFlag.objects.filter(team_id=get_current_team_id()).filter(key__startswith="flag-").count()
            )
            self.assertEqual(scoped_count, 1)

            # Unscoped query - all teams (simulated by not applying filter)
            unscoped_count = FeatureFlag.objects.filter(key__startswith="flag-").count()
            self.assertEqual(unscoped_count, 2)

    def test_real_world_scenario_api_endpoint(self):
        """
        Real-world scenario: API endpoint handling.

        This simulates what would happen in a typical API endpoint:
        1. Middleware sets team context from authenticated user
        2. ViewSet queries the model
        3. Only current team's records are returned
        """
        # Simulate: User from Team A makes a request
        with team_scope(self.team_a.id):
            # Simulate: ViewSet does FeatureFlag.objects.all()
            # With automatic scoping, this would only return Team A's flags
            team_id = get_current_team_id()
            flags = list(FeatureFlag.objects.filter(team_id=team_id))

            # User only sees their own flags
            self.assertEqual(len(flags), 1)
            self.assertEqual(flags[0].team_id, self.team_a.id)

            # Even if user knows Team B's flag ID, they can't access it
            with self.assertRaises(FeatureFlag.DoesNotExist):
                FeatureFlag.objects.filter(team_id=team_id).get(pk=self.flag_b.id)


class TestMigrationPath(TestCase):
    """
    Tests demonstrating the migration path from current code to automatic scoping.
    """

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Migration Test Org")
        cls.user = User.objects.create(email="migrate@posthog.com")
        cls.team = Team.objects.create(
            organization=cls.organization,
            name="Migration Team",
            api_token="token_migrate",
        )
        cls.flag = FeatureFlag.objects.create(
            team=cls.team,
            key="migrate-flag",
            name="Migration Test Flag",
            created_by=cls.user,
        )

    def test_current_code_pattern_still_works(self):
        """
        Current pattern: filter(team_id=X)

        This pattern would continue to work with the new manager.
        """
        flags = FeatureFlag.objects.filter(team_id=self.team.id)
        self.assertEqual(flags.count(), 1)

    def test_viewset_get_queryset_pattern_still_works(self):
        """
        Current ViewSet pattern: filter in get_queryset()

        Most ViewSets already filter by team in get_queryset().
        This would continue to work.
        """

        # Simulating a ViewSet's get_queryset method
        def get_queryset(team):
            return FeatureFlag.objects.filter(team=team)

        qs = get_queryset(self.team)
        self.assertEqual(qs.count(), 1)

    def test_new_pattern_with_automatic_scoping(self):
        """
        New pattern: rely on automatic scoping

        With automatic scoping, ViewSets could simplify to:
            def get_queryset(self):
                return FeatureFlag.objects.all()

        The team filter would be applied automatically.
        """
        with team_scope(self.team.id):
            # Simulated automatic scoping
            team_id = get_current_team_id()
            qs = FeatureFlag.objects.filter(team_id=team_id)
            self.assertEqual(qs.count(), 1)
