from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import ORGANIZATION_NAME, TEAM_NAME, create_demo_data
from posthog.models import PersonalAPIKey, Plugin, PluginConfig, PluginSourceFile, User
from posthog.models.event_definition import EventDefinition
from posthog.models.property_definition import PropertyDefinition


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-data", action="store_true", help="Create demo account without data",
        )
        parser.add_argument(
            "--create-e2e-test-plugin", action="store_true", help="Create plugin for charts E2E test",
        )

    def handle(self, *args, **options):
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
            PropertyDefinition.objects.create(team=team, name="$current_url")
            PropertyDefinition.objects.create(team=team, name="$browser")
            PropertyDefinition.objects.create(team=team, name="$os")
            PropertyDefinition.objects.create(team=team, name="usage_count", is_numerical=True)
            PropertyDefinition.objects.create(team=team, name="volume", is_numerical=True)
            PropertyDefinition.objects.create(team=team, name="is_first_movie")

            PersonalAPIKey.objects.create(user=user, label="e2e_demo_api_key key", value="e2e_demo_api_key")
            if not options["no_data"]:
                create_demo_data(team)

            if options["create_e2e_test_plugin"]:
                self.create_plugin(team)

    def create_plugin(self, team):
        plugin = Plugin.objects.create(organization=team.organization, name="e2e test plugin", plugin_type="source")
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=team, order=1, config={})

        PluginSourceFile.objects.update_or_create(
            plugin=plugin, filename="plugin.json", source='{ "name": "e2e test plugin", "config": [] }',
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
