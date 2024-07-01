from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

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
)
from posthog.models.event_definition import EventDefinition
from posthog.models.personal_api_key import hash_key_value
from posthog.models.property_definition import PropertyDefinition


domain = "zlwaterfield.com"
saml_entity_id = "http://www.okta.com/exkfso4f5a5yoH2u9697"
saml_acs_url = "https://trial-4372086.okta.com/app/trial-4372086_posthogdev_1/exkfso4f5a5yoH2u9697/sso/saml"
saml_x509_cert = """-----BEGIN CERTIFICATE-----
MIIDqjCCApKgAwIBAgIGAZBLKqqTMA0GCSqGSIb3DQEBCwUAMIGVMQswCQYDVQQGEwJVUzETMBEG
A1UECAwKQ2FsaWZvcm5pYTEWMBQGA1UEBwwNU2FuIEZyYW5jaXNjbzENMAsGA1UECgwET2t0YTEU
MBIGA1UECwwLU1NPUHJvdmlkZXIxFjAUBgNVBAMMDXRyaWFsLTQzNzIwODYxHDAaBgkqhkiG9w0B
CQEWDWluZm9Ab2t0YS5jb20wHhcNMjQwNjI0MTY1MjI1WhcNMzQwNjI0MTY1MzI1WjCBlTELMAkG
A1UEBhMCVVMxEzARBgNVBAgMCkNhbGlmb3JuaWExFjAUBgNVBAcMDVNhbiBGcmFuY2lzY28xDTAL
BgNVBAoMBE9rdGExFDASBgNVBAsMC1NTT1Byb3ZpZGVyMRYwFAYDVQQDDA10cmlhbC00MzcyMDg2
MRwwGgYJKoZIhvcNAQkBFg1pbmZvQG9rdGEuY29tMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIB
CgKCAQEAyu0MtzvMc2PGntBiQco1NnQ4579mhX4yzkDEyYpu0d8B/+5D5z28vJUdwlNeUhGWDtLp
Ihkm1lQmAQcC7mNn1jlkeKVnD+O3hqkNV/0PBcbXqdOQt2gkLpj5sVL00MOWkeMDFl8ri+dRMOXI
xUNWwAEWwXO4EUbNKwtAtTj/ljj5kp/HtVT7urOuPI+KZ5QYt0YSqGwx7QpM4lWzGrgkyjjzynXh
sJAJSp7hs7hvOj4aGAPGrGFcI65Dcelk3xAAanWuV90nBtkBDwQFP8WZ88WEdGEcaveiN/7fRDQH
wrq07N5F/+mGKz3x/NVruWYut9sHXBLyG0QZwys3Ggn59QIDAQABMA0GCSqGSIb3DQEBCwUAA4IB
AQBEprZUQnbUM5p5z2PX2ha5rkkDle7gccDS2WHljI+a7dRSoSMZHY0r7mxmG4pFwdwagSAC/lsu
7RFT32SCx3Mwyqny6hcH7AXlL30E1uyigoH7lazO2l3wyuua+7K6CwILXLr/6ScER1x81BjgVmhS
tjFgjwkc2ctYxN64kNoKqaFl1F+gAuECDQRJhSZICOwbVw1U1qSwCL4wdAS8W38tw1AcVU3KAHAC
X3vH90EFur/PknsPfdTURSm/n4RV3u/MJ3Ps/VGmXYY2ABoe7cwAWgzqecgXnrK5mnY3ryCg6VBT
Nh4dhjP5ATQ7YSgOcL5AR4TJ0J/08PDosZTMYxKB
-----END CERTIFICATE-----"""

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

            saml_organization = Organization.objects.create(
                name="saml org",
                available_product_features=[
                    {"key": "saml", "name": "SAML"}, 
                    {"key": "sso_enforcement", "name": "SSO Enforcement"},
                    {"key": "automatic_provisioning", "name": "Automatic Provisioning"},
                    {"key": "social_sso", "name": "Social SSO"}
                ],
            )
            OrganizationDomain.objects.create(
                organization=saml_organization,
                domain=domain,
                verified_at=timezone.now(),
                jit_provisioning_enabled=True,
                sso_enforcement="saml",
                saml_entity_id=saml_entity_id,
                saml_acs_url=saml_acs_url,
                saml_x509_cert=saml_x509_cert,
            )

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
