from datetime import timedelta

from posthog.test.base import NonAtomicTestMigrations

from django.utils import timezone

from posthog.models.utils import generate_random_token_personal, hash_key_value

GATEWAY_SCOPE = "llm_gateway:read"


class BackfillCredentialGatewayBindingsTest(NonAtomicTestMigrations):
    migrate_from = "1216_backfill_default_gateways"
    migrate_to = "1217_backfill_credential_gateway_bindings"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps):
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        Gateway = apps.get_model("posthog", "Gateway")
        PersonalAPIKey = apps.get_model("posthog", "PersonalAPIKey")

        org = Organization.objects.create(name="o")
        project = Project.objects.create(id=987654321, organization=org, name="p")
        self.team = Team.objects.create(id=project.id, name="t", organization=org, project=project)
        # The provision-on-create signal targets the real Team class, not this
        # historical one, so create the default gateway explicitly.
        # Historical Gateway's default manager is `all_teams`, so there's no `.objects`.
        self.default_gateway = Gateway._default_manager.create(team=self.team, slug="default", is_default=True)
        user = User.objects.create(email="u@example.com", current_team=self.team)

        self.eligible = PersonalAPIKey.objects.create(
            label="eligible",
            user=user,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=[GATEWAY_SCOPE],
        )
        self.ineligible = PersonalAPIKey.objects.create(
            label="ineligible",
            user=user,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=["feature_flag:read"],
        )

        # OAuth scope lives on issued tokens; the migration binds the application.
        OAuthApplication = apps.get_model("posthog", "OAuthApplication")
        OAuthAccessToken = apps.get_model("posthog", "OAuthAccessToken")
        expires = timezone.now() + timedelta(hours=1)

        self.eligible_app = self._make_app(OAuthApplication, org, user, "elig")
        OAuthAccessToken.objects.create(
            user=user, application=self.eligible_app, token="tok-elig", expires=expires, scope=GATEWAY_SCOPE
        )
        self.ineligible_app = self._make_app(OAuthApplication, org, user, "inelig")
        OAuthAccessToken.objects.create(
            user=user, application=self.ineligible_app, token="tok-inelig", expires=expires, scope="feature_flag:read"
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

    def test_binds_only_eligible_personal_keys(self):
        PersonalAPIKey = self.apps.get_model("posthog", "PersonalAPIKey")  # type: ignore

        eligible = PersonalAPIKey.objects.get(pk=self.eligible.pk)
        ineligible = PersonalAPIKey.objects.get(pk=self.ineligible.pk)

        self.assertEqual(eligible.gateway_id, self.default_gateway.pk)
        self.assertIsNone(ineligible.gateway_id)

    def test_binds_only_oauth_apps_with_an_eligible_token(self):
        OAuthApplication = self.apps.get_model("posthog", "OAuthApplication")  # type: ignore

        eligible = OAuthApplication.objects.get(pk=self.eligible_app.pk)
        ineligible = OAuthApplication.objects.get(pk=self.ineligible_app.pk)

        self.assertEqual(eligible.gateway_id, self.default_gateway.pk)
        self.assertIsNone(ineligible.gateway_id)
