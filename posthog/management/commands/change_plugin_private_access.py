import uuid
import logging

from django.core.management import CommandError
from django.core.management.base import BaseCommand

import structlog

from posthog.models import Organization
from posthog.models.plugin import Plugin

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Change Plugin private access (either add or remove depending on state)."

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", default=None, type=uuid.UUID, help="Specify the organization.")
        parser.add_argument("--plugin-id", default=None, type=int, help="Specify the plugin.")
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]

    if options["plugin_id"] is None:
        raise CommandError("You must specify --plugin-id to run this script")

    if options["organization_id"] is None:
        raise CommandError("You must specify --organization-id to run this script")

    plugin_id = options["plugin_id"]
    organization_id = options["organization_id"]

    plugin = Plugin.objects.get(pk=plugin_id)
    current_organizations = plugin.has_private_access.all()
    logger.info(
        f"Plugin {plugin.name} is currently explicitly allowed for organizations: [{', '.join([str(org.name) for org in current_organizations])}]"
    )

    org = Organization.objects.get(pk=organization_id)
    org_current_plugins = org.plugin_set.all()
    logger.info(
        f"Organization {org.name} currently has explicit access to plugins: [{', '.join([str(plugin.name) for plugin in org_current_plugins])}]"
    )

    has_access = org in current_organizations
    logger.info(
        f"Target organization {organization_id} is named {org.name} currently {'has access' if has_access else 'does not have access'}"
    )

    if has_access:
        if live_run:
            plugin.has_private_access.remove(org)
            logger.info("Removed access")
        else:
            logger.info("Skipping the access removal, pass --live-run to run it")
    else:
        if live_run:
            plugin.has_private_access.add(org)
            logger.info("Added access")
        else:
            logger.info("Skipping the access addition, pass --live-run to run it")
