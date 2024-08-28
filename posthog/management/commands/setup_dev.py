from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.conf import settings

from posthog.demo.legacy import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import (
    EventProperty,
    PersonalAPIKey,
    Plugin,
    PluginConfig,
    PluginSourceFile,
    Team,
    User,
    OrganizationDomain,
    Organization,
    Project,
)
from posthog.models.event_definition import EventDefinition
from posthog.models.personal_api_key import hash_key_value
from posthog.models.property_definition import PropertyDefinition


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def add_arguments(self, parser):
        parser.add_argument("--no-data", action="store_true", help="Create demo account without data")
        parser.add_argument(
            "--create-e2e-test-plugin",
            action="store_true",
            help="Create plugin for charts E2E test",
        )

    def handle(self, *args, **options):
        print("\n⚠️ setup_dev is deprecated. Use the more robust generate_demo_data command instead.\n")  # noqa T201
        with transaction.atomic():
            _, team, user = User.objects.bootstrap(
                organization_name=ORGANIZATION_NAME,
                email="test@posthog.com",
                password="12345678",
                first_name="Jane Doe",
                is_staff=True,
                team_fields={
                    "name": TEAM_NAME,
                    "api_token": "e2e_token_1239",
                    "completed_snippet_onboarding": True,
                    "ingested_event": True,
                },
            )
            EventDefinition.objects.create(team=team, name="$pageview")
            EventDefinition.objects.create(team=team, name="$autocapture")
            self.add_property_definition(team, "$current_url")
            self.add_property_definition(team, "$browser")
            self.add_property_definition(team, "$os")
            self.add_property_definition(team, "usage_count")
            self.add_property_definition(team, "volume")
            self.add_property_definition(team, "is_first_movie")
            PropertyDefinition.objects.create(name="name", type=PropertyDefinition.Type.PERSON, team=team)
            PropertyDefinition.objects.create(name="is_demo", type=PropertyDefinition.Type.PERSON, team=team)

            PersonalAPIKey.objects.create(
                user=user,
                label="e2e_demo_api_key key",
                secure_value=hash_key_value("e2e_demo_api_key"),
            )
            if not options["no_data"]:
                create_demo_data(team)

            if options["create_e2e_test_plugin"]:
                self.create_plugin(team)

            required_settings = [
                "E2E_SAML_ORGANIZATION_DOMAIN_ID",
                "E2E_SAML_DOMAIN",
                "E2E_SAML_ENTITY_ID",
                "E2E_SAML_ACS_URL",
                "E2E_SAML_X509_CERT",
            ]

            if all(hasattr(settings, attr) for attr in required_settings):
                saml_organization = Organization.objects.create(
                    name="saml org",
                    available_product_features=[
                        {"key": "saml", "name": "SAML"},
                        {"key": "sso_enforcement", "name": "SSO Enforcement"},
                        {"key": "automatic_provisioning", "name": "Automatic Provisioning"},
                        {"key": "social_sso", "name": "Social SSO"},
                    ],
                )
                _, team = Project.objects.create_with_team(
                    organization=saml_organization,
                    name="saml project",
                    team_fields={"name": "saml team"},
                )

                domain = OrganizationDomain.objects.create(
                    id=settings.E2E_SAML_ORGANIZATION_DOMAIN_ID,
                    organization=saml_organization,
                    domain=settings.E2E_SAML_DOMAIN,
                    verified_at=timezone.now(),
                    jit_provisioning_enabled=True,
                    sso_enforcement="saml",
                    saml_entity_id=settings.E2E_SAML_ENTITY_ID,
                    saml_acs_url=settings.E2E_SAML_ACS_URL,
                    saml_x509_cert=settings.E2E_SAML_X509_CERT,
                )
                print(
                    "DEBUG: last 6 characters of (saml_x509_cert) is ",
                    domain.saml_x509_cert[-36:],
                    "\n\tsettings.E2E_SAML_X509_CERT is ",
                    settings.E2E_SAML_X509_CERT[-36:],
                )  # noqa T201
            else:
                print("Warning: Not all required SAML settings are set. Skipping OrganizationDomain creation.")  # noqa T201

    @staticmethod
    def add_property_definition(team: Team, property: str) -> None:
        PropertyDefinition.objects.create(team=team, name=property)
        EventProperty.objects.create(team=team, event="$pageview", property=property)
        EventProperty.objects.create(team=team, event="$autocapture", property=property)

    def create_plugin(self, team):
        plugin = Plugin.objects.create(organization=team.organization, name="e2e test plugin", plugin_type="source")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=team, order=1, config={})

        PluginSourceFile.objects.update_or_create(
            plugin=plugin,
            filename="plugin.json",
            source='{ "name": "e2e test plugin", "config": [] }',
        )
        PluginSourceFile.objects.update_or_create(
            plugin=plugin,
            filename="index.ts",
            source="""
                export async function onEvent(event, meta) {
                    const ratelimit = await meta.cache.get('ratelimit')
                    if (!ratelimit && event.event !== '$pluginEvent') {
                        posthog.capture('$pluginEvent', { event: event.event })
                        await meta.cache.set('ratelimit', 1)
                        await meta.cache.expire('ratelimit', 60)
                    }
                }
            """,
        )

        plugin_config.enabled = True
        plugin_config.save()
