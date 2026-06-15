from datetime import timedelta

from posthog.test.base import NonAtomicTestMigrations

from django.utils import timezone

from posthog.models.utils import generate_random_token_secret, hash_key_value

GATEWAY_SCOPE = "llm_gateway:read"


class BackfillCredentialGatewayBindingsTest(NonAtomicTestMigrations):
    migrate_from = "1222_backfill_default_gateways"
    migrate_to = "1223_backfill_credential_gateway_bindings"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        Gateway = apps.get_model("posthog", "Gateway")
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        OAuthAccessToken = apps.get_model("posthog", "OAuthAccessToken")
        ProjectSecretAPIKey = apps.get_model("posthog", "ProjectSecretAPIKey")

        # A single-root org → its root team is the one unambiguous gateway owner.
        org_solo = Organization.objects.create(name="solo", slug="solo")
        project_solo = Project.objects.create(id=987654321, organization=org_solo, name="psolo")
        self.team_solo = Team.objects.create(
            id=project_solo.id, name="tsolo", organization=org_solo, project=project_solo
        )
        # Provision-on-create targets the real Team, not this historical one, so seed
        # the gateway explicitly. Historical Gateway's default manager is `all_teams`.
        self.default_gateway_solo = Gateway._default_manager.create(team=self.team_solo, slug="default")
        user = User.objects.create(email="u@example.com", current_team=self.team_solo)

        expires = timezone.now() + timedelta(hours=1)

        # Scope lives on issued tokens; the migration binds the app to its org root's gateway.
        self.eligible_app = self._make_app(OAuthApplication, org_solo, user, "elig")
        OAuthAccessToken.objects.create(
            user=user, application=self.eligible_app, token="tok-elig", expires=expires, scope=GATEWAY_SCOPE
        )
        self.ineligible_app = self._make_app(OAuthApplication, org_solo, user, "inelig")
        OAuthAccessToken.objects.create(
            user=user, application=self.ineligible_app, token="tok-inelig", expires=expires, scope="feature_flag:read"
        )

        # Multi-root org (two root teams) → ambiguous, so an eligible app stays unbound.
        org_multi = Organization.objects.create(name="multi", slug="multi")
        for project_id, name in ((987654322, "p1"), (987654323, "p2")):
            project = Project.objects.create(id=project_id, organization=org_multi, name=name)
            team = Team.objects.create(id=project.id, name=name, organization=org_multi, project=project)
            Gateway._default_manager.create(team=team, slug="default")
        self.multiroot_app = self._make_app(OAuthApplication, org_multi, user, "multi")
        OAuthAccessToken.objects.create(
            user=user, application=self.multiroot_app, token="tok-multi", expires=expires, scope=GATEWAY_SCOPE
        )

        # Project secret keys are never backfilled — even an eligible one stays unbound.
        self.secret_key = ProjectSecretAPIKey.objects.create(
            label="secret",
            team=self.team_solo,
            secure_value=hash_key_value(generate_random_token_secret()),
            scopes=[GATEWAY_SCOPE],
        )

    @staticmethod
    def _make_app(OAuthApplication, org, user, client_id):
        return OAuthApplication.objects.create(
            name=client_id,
            client_id=client_id,
            client_type="confidential",
            authorization_grant_type="authorization-code",
            redirect_uris="https://example.com/cb",
            algorithm="RS256",
            organization=org,
            user=user,
        )

    def test_binds_only_oauth_apps_with_an_eligible_token(self):
        OAuthApplication = self.apps.get_model("posthog", "OAuthApplication")  # type: ignore

        eligible = OAuthApplication.objects.get(pk=self.eligible_app.pk)
        ineligible = OAuthApplication.objects.get(pk=self.ineligible_app.pk)

        self.assertEqual(eligible.gateway_id, self.default_gateway_solo.pk)
        self.assertIsNone(ineligible.gateway_id)

    def test_leaves_oauth_app_unbound_when_org_has_multiple_root_teams(self):
        OAuthApplication = self.apps.get_model("posthog", "OAuthApplication")  # type: ignore

        multiroot = OAuthApplication.objects.get(pk=self.multiroot_app.pk)
        self.assertIsNone(multiroot.gateway_id)

    def test_does_not_backfill_project_secret_keys(self):
        ProjectSecretAPIKey = self.apps.get_model("posthog", "ProjectSecretAPIKey")  # type: ignore

        secret_key = ProjectSecretAPIKey.objects.get(pk=self.secret_key.pk)
        self.assertIsNone(secret_key.gateway_id)
