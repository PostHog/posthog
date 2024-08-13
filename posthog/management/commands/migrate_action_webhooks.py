import re
from typing import Optional
from django.core.management.base import BaseCommand

from posthog.cdp.validation import compile_hog, validate_inputs
from posthog.models.action.action import Action
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.cdp.templates.webhook.template_webhook import template as webhook_template

# Maps to a string or a tuple of name and url
mappings: dict[str, str | list[str]] = {
    "[event]": ["{event.name}", "{event.url}"],
    "[event.link]": "{event.url}",
    "[event.event]": "{event.name}",
    "[event.uuid]": "{event.uuid}",
    "[person]": ["{person.name}", "{person.url}"],
    "[person.link]": "{person.url}",
}


def convert_link(text: str, url: str, is_slack: bool) -> str:
    if is_slack:
        return f"<{url}|{text}>"
    return f"[{text}]({url})"


def convert_slack_message_format_to_hog(action: Action, is_slack: bool) -> tuple[str, str]:
    message_format = action.slack_message_format or "[action.name] triggered by [person]"
    matches = re.findall(r"(\[[^\]]+\])", message_format)
    markdown = message_format
    text = message_format

    # Iterate over each match replacing it with the appropriate hog format
    for match in matches:
        content = match[1:-1]
        if match in mappings:
            if isinstance(mappings[match], list):
                # For markdown we create a link
                markdown = markdown.replace(match, convert_link(mappings[match][0], mappings[match][1], is_slack))
                # For text we just replace it with the name
                text = text.replace(match, mappings[match][0])
            else:
                markdown = markdown.replace(match, f"{{{content}}}")
                text = text.replace(match, f"{{{content}}}")
        elif match.startswith("[action."):
            # Action data is no longer available as it is just a filter hence we need to replace it with static values
            action_property = content.split(".")[1]
            action_url = f"{{project.url}}/data-management/actions/{action.id}"
            if action_property == "link":
                text = text.replace(match, action_url)
                markdown = markdown.replace(match, action_url)
            else:
                markdown = markdown.replace(match, convert_link(action.name, action_url, is_slack))
                text = text.replace(match, action.name)
        elif match.startswith("[groups."):
            parts = content.split(".")
            if len(parts) == 2:
                # this means it is a link to the group - we just need to append "url"
                markdown = markdown.replace(match, f"{{{content}.url}}")
                text = text.replace(match, f"{{{content}.url}}")
            else:
                # Only other supported thing is properties which happens to match the format
                markdown = markdown.replace(match, f"{{{content}}}")
                text = text.replace(match, f"{{{content}}}")

        else:
            markdown = markdown.replace(match, f"{{{content}}}")
            text = text.replace(match, f"{{{content}}}")

    print(
        "Converted message format:",
        {
            "original": message_format,
            "markdown": markdown,
            "text": text,
        },
    )
    return (markdown, text)


def convert_to_hog_function(action: Action) -> Optional[HogFunction]:
    webhook_url = action.team.slack_incoming_webhook

    if not webhook_url:
        print(f"No slack_incoming_webhook set for team {action.team_id}, skipping action {action.id}")
        return None

    message_markdown, message_text = convert_slack_message_format_to_hog(action, is_slack="slack" in webhook_url)

    if "slack" in webhook_url:
        body = {
            "text": message_text,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": message_markdown}}],
        }
    else:
        body = {
            "text": message_markdown,
        }

    hog_function = HogFunction(
        name=f"Webhook for action {action.id} ({action.name})",
        description="Automatically migrated webhook from legacy action",
        team_id=action.team_id,
        inputs=validate_inputs(
            webhook_template.inputs_schema,
            {"url": {"value": webhook_url}, "method": {"value": "POST"}, "body": {"value": body}},
        ),
        inputs_schema=webhook_template.inputs_schema,
        template_id=webhook_template.id,
        hog=webhook_template.hog,
        bytecode=compile_hog(webhook_template.hog),
        filters={"actions": [{"id": f"{action.id}", "type": "actions", "name": action.name, "order": 0}]},
        enabled=True,
    )
    return hog_function


def migrate_action_webhooks(action_ids: list[int], team_ids: list[int], dry_run: bool = False):
    if action_ids and team_ids:
        print("Please provide either action_ids or team_ids, not both")
        return

    query = Action.objects.select_related("team").filter(post_to_slack=True)

    if team_ids:
        print("Migrating all actions for teams:", team_ids)
        query = query.filter(team_id__in=team_ids)
    elif action_ids:
        print("Migrating actions:", action_ids)
        query = query.filter(id__in=action_ids)
    else:
        print(f"Migrating all actions")  # noqa T201

    hog_functions: list[HogFunction] = []
    actions = list(query.all())

    for index, action in enumerate(actions):
        print(f"Processing action {action.id}")
        hog_function = convert_to_hog_function(action)
        if hog_function:
            hog_functions.append(hog_function)

    if not dry_run:
        HogFunction.objects.bulk_create(hog_functions)
    else:
        print("Would have created the following HogFunctions:")
        for hog_function in hog_functions:
            print(hog_function, hog_function.inputs, hog_function.filters)

    print("Done")  # noqa T201


class Command(BaseCommand):
    help = "Migrate action webhooks to HogFunctions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            type=bool,
            help="If set, will not actually perform the migration, but will print out what would have been done",
        )
        parser.add_argument("--action-ids", type=str, help="Comma separated list of action ids to sync")
        parser.add_argument("--team-ids", type=str, help="Comma separated list of team ids to sync")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        action_ids = options["action_ids"]
        team_ids = options["team_ids"]

        if action_ids and team_ids:
            print("Please provide either action_ids or team_ids, not both")
            return

        migrate_action_webhooks(
            action_ids=[int(x) for x in action_ids.split(",")] if action_ids else [],
            team_ids=[int(x) for x in team_ids.split(",")] if team_ids else [],
            dry_run=dry_run,
        )
