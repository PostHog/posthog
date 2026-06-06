from posthog.test.base import NonAtomicTestMigrations

from posthog.models.utils import generate_random_token_personal, hash_key_value

GATEWAY_SCOPE = "llm_gateway:read"


class BackfillCredentialGatewayBindingsTest(NonAtomicTestMigrations):
    migrate_from = "1213_backfill_default_gateways"
    migrate_to = "1215_backfill_credential_gateway_bindings"

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

    def test_binds_only_eligible_credentials(self):
        PersonalAPIKey = self.apps.get_model("posthog", "PersonalAPIKey")  # type: ignore

        eligible = PersonalAPIKey.objects.get(pk=self.eligible.pk)
        ineligible = PersonalAPIKey.objects.get(pk=self.ineligible.pk)

        self.assertEqual(eligible.gateway_id, self.default_gateway.pk)
        self.assertIsNone(ineligible.gateway_id)
