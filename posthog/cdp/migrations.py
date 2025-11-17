import json
from typing import Any

from django.db import transaction
from django.db.models import Q

from posthog.api.hog_function import HogFunctionSerializer
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginAttachment, PluginConfig
from posthog.models.team.team import Team

# python manage.py migrate_plugins_to_hog_functions --dry-run --test-mode --kind=transformation


def migrate_batch(legacy_plugins: Any, kind: str, test_mode: bool, dry_run: bool):
    hog_functions = []
    teams_cache: dict[int, Team] = {}

    with transaction.atomic():
        for plugin_config in legacy_plugins:
            print(  # noqa: T201
                "Migrating plugin",
                plugin_config["id"],
                plugin_config["plugin__name"],
                plugin_config["plugin__capabilities"],
            )

            print("Attempting to migrate plugin", plugin_config)  # noqa: T201
            url: str = plugin_config["plugin__url"] or ""

            if not url:
                print("Skipping plugin", plugin_config["plugin__name"], "as it doesn't have a url")  # noqa: T201
                continue

            plugin_id = url.replace("inline://", "").replace("https://github.com/PostHog/", "")
            plugin_name = plugin_config["plugin__name"]

            # Inline plugins are named slightly differently so we fix it here
            if plugin_id == "semver-flattener":
                plugin_id = "semver-flattener-plugin"
            if plugin_id == "user-agent":
                plugin_id = "user-agent-plugin"

            if test_mode:
                plugin_name = f"[CDP-TEST-HIDDEN] {plugin_name}"

            inputs = {}

            # Iterate over the plugin config to build the inputs

            for key, value in plugin_config["config"].items():
                inputs[key] = {"value": value}

            if plugin_id == "first-time-event-tracker" or plugin_id == "customerio-plugin":
                # These are plugins that use the legacy storage
                inputs["legacy_plugin_config_id"] = {"value": str(plugin_config["id"])}

            if len(plugin_config["config"]) > 0:
                # Load all attachments for this plugin config if there is some config
                attachments = PluginAttachment.objects.filter(plugin_config_id=plugin_config["id"])

                for attachment in attachments:
                    contents: Any = attachment.parse_contents()
                    try:
                        contents = json.loads(contents)
                    except Exception as e:
                        print("Error parsing attachment", attachment.key, e)  # noqa: T201

                    if contents:
                        inputs[attachment.key] = {"value": contents}

            team = teams_cache.get(plugin_config["team_id"]) or Team.objects.get(id=plugin_config["team_id"])
            if not team:
                raise Exception(f"Team not found: {plugin_config['team_id']}")

            teams_cache[plugin_config["team_id"]] = team

            serializer_context = {
                "team": team,
                "get_team": (lambda t=team: t),
                "is_create": True,
            }

            template = HogFunctionTemplate.objects.get(template_id=f"plugin-{plugin_id}")

            if not template:
                raise Exception(f"Template not found for plugin {plugin_id}")

            if HogFunction.objects.filter(
                template_id=template.id, type=kind, team_id=team.id, enabled=True, deleted=False
            ).exists():
                print(f"Skipping plugin {plugin_name} as it already exists as a hog function")  # noqa: T201
                continue

            data = {
                "template_id": template.template_id,
                "type": kind,
                "name": plugin_name,
                "description": template.description,
                "filters": template.filters,
                "hog": template.code,
                "inputs": inputs,
                "enabled": True,
                "icon_url": template.icon_url,
                "inputs_schema": template.inputs_schema,
                "execution_order": plugin_config["order"],
            }

            print("Attempting to create hog function...")  # noqa: T201
            print(json.dumps(data, indent=2))  # noqa: T201

            serializer = HogFunctionSerializer(
                data=data,
                context=serializer_context,
            )
            serializer.is_valid(raise_exception=True)
            hog_functions.append(HogFunction(**serializer.validated_data))

        print(hog_functions)  # noqa: T201

        if not hog_functions:
            print("No hog functions to create")  # noqa: T201
            return []

        if dry_run:
            print("Dry run, not creating hog functions")  # noqa: T201
            return hog_functions

        print("Creating hog functions")  # noqa: T201
        HogFunction.objects.bulk_create(hog_functions)

        if not test_mode:
            print("Disabling old plugins")  # noqa: T201
            # Disable the old plugins
            PluginConfig.objects.filter(id__in=[plugin_config["id"] for plugin_config in legacy_plugins]).update(
                enabled=False
            )

        print("Done")  # noqa: T201

        return hog_functions


def migrate_legacy_plugins(
    dry_run=True, team_ids=None, test_mode=True, kind: str = "transformation", batch_size=100, limit: int | None = None
):
    # Get all legacy plugin_configs that are active with their attachments and global values
    # Plugins are huge (JS and assets) so we only grab the bits we really need

    legacy_plugin_ids = PluginConfig.objects.values("id").filter(enabled=True, deleted=False).order_by("-id").all()

    if kind == "destination":
        legacy_plugin_ids = legacy_plugin_ids.filter(
            Q(plugin__capabilities__methods__contains=["onEvent"])
            | Q(plugin__capabilities__methods__contains=["composeWebhook"])
        )
    elif kind == "transformation":
        legacy_plugin_ids = legacy_plugin_ids.filter(plugin__capabilities__methods__contains=["processEvent"])
    else:
        raise ValueError(f"Invalid kind: {kind}")

    if team_ids:
        team_ids = [int(id) for id in team_ids.split(",")]
        legacy_plugin_ids = legacy_plugin_ids.filter(team_id__in=team_ids)

    if limit:
        legacy_plugin_ids = legacy_plugin_ids[:limit]

    # Do this in batches of batch_size but loading the individual plugin configs as we are modfiying them in the loop

    for i in range(0, len(legacy_plugin_ids), batch_size):
        batch = legacy_plugin_ids[i : i + batch_size]
        legacy_plugins = PluginConfig.objects.values(
            "id",
            "config",
            "team_id",
            "plugin__name",
            "plugin__url",
            "plugin__capabilities",
            "plugin__config_schema",
            "plugin__icon",
            "order",
            # Order by order asc but with nulls last
        ).filter(id__in=[x["id"] for x in batch])

        migrate_batch(legacy_plugins, kind, test_mode, dry_run)
