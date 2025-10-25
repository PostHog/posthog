from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo.legacy import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import EventProperty, PersonalAPIKey, Plugin, PluginConfig, PluginSourceFile, Team, User
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
                    "surveys_opt_in": True,
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
