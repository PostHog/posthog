from contextlib import AbstractContextManager

from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.scoping import team_scope
from posthog.models.team.team import Team


class _TeamScopedTestMixin:
    """Wrap setUp/tearDown in team_scope so test-body queries to the
    TeamScopedRootMixin-backed Gateway find a team context."""

    _team_scope_cm: AbstractContextManager[None] | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        cm = team_scope(self.team.id)  # type: ignore[attr-defined]
        cm.__enter__()
        self._team_scope_cm = cm
        # The provision-on-create signal already gave self.team a default gateway;
        # clear all rows so these model-unit tests control their own fixtures.
        Gateway.all_teams.all().delete()

    def tearDown(self) -> None:
        if self._team_scope_cm is not None:
            try:
                self._team_scope_cm.__exit__(None, None, None)
            finally:
                self._team_scope_cm = None
        super().tearDown()  # type: ignore[misc]


class TestGatewayModel(_TeamScopedTestMixin, BaseTest):
    def test_create_with_valid_slug(self):
        gateway = Gateway.objects.create(team=self.team, slug=DEFAULT_GATEWAY_SLUG, is_default=True)
        self.assertEqual(gateway.slug, "default")
        self.assertEqual(gateway.team_id, self.team.id)

    @parameterized.expand(["posthog_code", "slack-app", "wizard", "v2", "a", "default"])
    def test_accepts_lowercase_url_safe_slugs(self, slug: str):
        gateway = Gateway.objects.create(team=self.team, slug=slug)
        self.assertEqual(gateway.slug, slug)

    @parameterized.expand(
        [
            ("uppercase", "Posthog_Code"),
            ("space", "slack app"),
            ("slash", "wizard/v2"),
            ("empty", ""),
            ("leading_underscore", "_leading"),
            ("trailing_hyphen", "trailing-"),
            ("double_separator", "a__b"),
        ]
    )
    def test_rejects_malformed_slug_on_save(self, _name: str, slug: str):
        with self.assertRaises(ValidationError):
            Gateway.objects.create(team=self.team, slug=slug)

    def test_slug_is_stripped_before_validation(self):
        gateway = Gateway.objects.create(team=self.team, slug="  posthog_code  ")
        self.assertEqual(gateway.slug, "posthog_code")

    def test_slug_unique_per_team(self):
        Gateway.objects.create(team=self.team, slug="posthog_code")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gateway.objects.create(team=self.team, slug="posthog_code")

    def test_same_slug_allowed_across_teams(self):
        other = Team.objects.create(organization=self.organization, name="other")
        Gateway.all_teams.filter(team=other).delete()  # drop other's auto-provisioned default
        Gateway.objects.create(team=self.team, slug=DEFAULT_GATEWAY_SLUG, is_default=True)
        # A different team reusing the same slug is fine — attribution is keyed
        # (team_id, slug), so team_id disambiguates.
        with team_scope(other.id):
            Gateway.objects.create(team=other, slug=DEFAULT_GATEWAY_SLUG, is_default=True)
        self.assertEqual(Gateway.objects.unscoped().filter(slug=DEFAULT_GATEWAY_SLUG).count(), 2)

    def test_one_default_per_team(self):
        Gateway.objects.create(team=self.team, slug="default", is_default=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gateway.objects.create(team=self.team, slug="posthog_code", is_default=True)

    def test_multiple_non_default_gateways_allowed(self):
        Gateway.objects.create(team=self.team, slug="default", is_default=True)
        Gateway.objects.create(team=self.team, slug="posthog_code")
        Gateway.objects.create(team=self.team, slug="wizard")
        self.assertEqual(Gateway.objects.filter(team=self.team).count(), 3)
