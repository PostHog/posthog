from contextlib import AbstractContextManager

from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from parameterized import parameterized

from posthog.models.gateway import DEFAULT_GATEWAY_SLUG, Gateway
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
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
        gateway = Gateway.objects.create(team=self.team, slug=DEFAULT_GATEWAY_SLUG)
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

    def test_rejects_slug_over_max_length(self):
        # The pattern alone doesn't bound length; save() also rejects an over-long
        # slug with a clean error rather than letting it hit the varchar(64) wall.
        with self.assertRaises(ValidationError):
            Gateway.objects.create(team=self.team, slug="a" * 65)

    def test_check_constraint_rejects_malformed_slug_bypassing_save(self):
        # bulk_create skips save()'s validator, so the DB CheckConstraint is the
        # last line of defence keeping a malformed slug off the billing ledger.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gateway.all_teams.bulk_create([Gateway(team=self.team, slug="Bad Slug")])

    def test_slug_is_stripped_before_validation(self):
        gateway = Gateway.objects.create(team=self.team, slug="  posthog_code  ")
        self.assertEqual(gateway.slug, "posthog_code")

    def test_slug_unique_per_team(self):
        Gateway.objects.create(team=self.team, slug="posthog_code")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Gateway.objects.create(team=self.team, slug="posthog_code")

    def test_same_slug_allowed_across_teams(self):
        other = Team.objects.create(organization=self.organization, name="other")
        Gateway.all_teams.filter(team=other).delete()  # drop other's auto-provisioned gateway
        Gateway.objects.create(team=self.team, slug=DEFAULT_GATEWAY_SLUG)
        # A different team reusing the same slug is fine — attribution is keyed
        # (team_id, slug), so team_id disambiguates.
        with team_scope(other.id):
            Gateway.objects.create(team=other, slug=DEFAULT_GATEWAY_SLUG)
        self.assertEqual(Gateway.objects.unscoped().filter(slug=DEFAULT_GATEWAY_SLUG).count(), 2)

    def test_multiple_gateways_allowed_per_team(self):
        Gateway.objects.create(team=self.team, slug="default")
        Gateway.objects.create(team=self.team, slug="posthog_code")
        Gateway.objects.create(team=self.team, slug="wizard")
        self.assertEqual(Gateway.objects.filter(team=self.team).count(), 3)

    def test_scoped_manager_excludes_other_teams_gateways(self):
        # The mixin pins team_scope to self.team, so the fail-closed `objects`
        # manager must never surface another team's gateways — the tenant boundary.
        other = Team.objects.create(organization=self.organization, name="other")
        Gateway.all_teams.filter(team=other).delete()  # drop other's auto-provisioned gateway
        with team_scope(other.id):
            Gateway.objects.create(team=other, slug="other_team_gateway")
        Gateway.objects.create(team=self.team, slug="my_gateway")
        self.assertEqual(set(Gateway.objects.values_list("slug", flat=True)), {"my_gateway"})
        self.assertEqual(Gateway.objects.filter(slug="other_team_gateway").count(), 0)

    def test_scoped_get_on_other_teams_gateway_raises(self):
        other = Team.objects.create(organization=self.organization, name="other")
        Gateway.all_teams.filter(team=other).delete()
        with team_scope(other.id):
            other_gateway = Gateway.objects.create(team=other, slug="other_team_gateway")
        # Out-of-scope lookup must fail closed, not leak the row.
        with self.assertRaises(Gateway.DoesNotExist):
            Gateway.objects.get(pk=other_gateway.pk)

    def test_key_cannot_bind_other_teams_gateway(self):
        other = Team.objects.create(organization=self.organization, name="other")
        with team_scope(other.id):
            other_gateway = Gateway.all_teams.get(team=other, slug=DEFAULT_GATEWAY_SLUG)
        # Binding a team-A key to team B's gateway would misattribute team A's spend.
        with self.assertRaises(ValueError):
            ProjectSecretAPIKey.objects.create(team=self.team, label="cross", gateway=other_gateway)

    def test_key_bound_to_missing_gateway_raises(self):
        # gateway_id pointing at a non-existent row surfaces a clear ValueError
        # rather than a bare Gateway.DoesNotExist from the team-match guard.
        with self.assertRaises(ValueError):
            ProjectSecretAPIKey.objects.create(
                team=self.team, label="missing", gateway_id="00000000-0000-0000-0000-000000000000"
            )

    def test_child_env_key_can_bind_parent_gateway(self):
        child = Team.objects.create(organization=self.organization, name="child", parent_team=self.team)
        gateway = Gateway.objects.create(team=self.team, slug="shared")
        # The gateway is project-scoped to the parent, so a child-env key shares it.
        key = ProjectSecretAPIKey.objects.create(team=child, label="child_key", gateway=gateway)
        self.assertEqual(key.gateway_id, gateway.id)

    def test_deleting_team_with_bound_gateway_cascades(self):
        victim = Team.objects.create(organization=self.organization, name="victim")
        gateway = Gateway.all_teams.get(team=victim, slug=DEFAULT_GATEWAY_SLUG)
        key = ProjectSecretAPIKey.objects.create(team=victim, label="k", gateway=gateway)
        # SET_NULL (not PROTECT): a bound credential no longer aborts the team teardown.
        victim.delete()
        self.assertFalse(Gateway.all_teams.filter(pk=gateway.pk).exists())
        self.assertFalse(ProjectSecretAPIKey.objects.filter(pk=key.pk).exists())
