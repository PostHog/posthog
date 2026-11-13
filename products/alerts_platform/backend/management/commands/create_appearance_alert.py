"""Creates an appearance alert with one Slack or webhook destination, for dogfooding before the UI exists.

Example, which announces new error patterns in the `api` service to a Slack channel:

    manage.py create_appearance_alert --team-id 2 --source logs --name "New api errors" \\
        --filter service_name=exact:api --filter severity_text=exact:error,fatal \\
        --slack-integration-id 123 --slack-channel-id C0123
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.alerts_platform.backend.facade.appearance import appearance_create_warning, create_appearance_alert
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationValidationError,
    AlertEventKind,
    DestinationType,
    InvalidPlatformAlertEdit,
    NewAlertDestination,
    SourceKind,
)

APPEARANCE_SOURCES = (SourceKind.LOGS.value, SourceKind.ERROR_TRACKING.value)


def parse_filter(raw: str) -> dict[str, Any]:
    """`key=operator:value,value`, such as `service_name=exact:api,web`."""
    key, separator, rest = raw.partition("=")
    operator, colon, values = rest.partition(":")
    if not separator or not colon or not key or not values:
        raise CommandError(f"A filter is key=operator:value[,value], not {raw!r}")
    return {"key": key, "operator": operator, "values": values.split(",")}


class Command(BaseCommand):
    help = "Create an appearance alert on the alerts platform, with one Slack or webhook destination."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--source", choices=APPEARANCE_SOURCES, required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--filter", action="append", default=[], dest="filters")
        parser.add_argument("--slack-integration-id", type=int)
        parser.add_argument("--slack-channel-id")
        parser.add_argument("--webhook-url")

    def handle(self, *args: Any, **options: Any) -> None:
        destination = _destination(options)
        source = SourceKind(options["source"])
        if warning := appearance_create_warning(options["team_id"], source):
            self.stderr.write(f"Warning: {warning}")
        try:
            view = create_appearance_alert(
                team_id=options["team_id"],
                source=source,
                name=options["name"],
                filters=[parse_filter(raw) for raw in options["filters"]],
                destinations=[NewAlertDestination(data=destination, event_kinds=(AlertEventKind.FIRING,))],
            )
        except (InvalidPlatformAlertEdit, AlertDestinationValidationError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(f"Created appearance alert {view.id}")


def _destination(options: dict[str, Any]) -> AlertDestinationData:
    if options["webhook_url"]:
        return AlertDestinationData(type=DestinationType.WEBHOOK, webhook_url=options["webhook_url"])
    if options["slack_integration_id"] and options["slack_channel_id"]:
        return AlertDestinationData(
            type=DestinationType.SLACK,
            slack_workspace_id=options["slack_integration_id"],
            slack_channel_id=options["slack_channel_id"],
        )
    raise CommandError("Pass --webhook-url, or --slack-integration-id with --slack-channel-id.")
