import json
from typing import Any
from posthog.api.hog_function import HogFunctionSerializer
from posthog.api.hog_function_template import HogFunctionTemplates
from posthog.constants import AvailableFeature
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginAttachment, PluginConfig
from posthog.models.team.team import Team
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator

# python manage.py migrate_plugins_to_hog_functions --dry-run --test-mode --kind=transformation


def migrate_batch(legacy_plugins: Any, kind: str, test_mode: bool, dry_run: bool):
    hog_functions = []
    plugin_configs_without_addon = []
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

            if plugin_id == "first-time-event-tracker":
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
                "bypass_addon_check": True,
                "is_create": True,
            }

            template = HogFunctionTemplates.template(f"plugin-{plugin_id}")

            if not template:
                raise Exception(f"Template not found for plugin {plugin_id}")

            data = {
                "template_id": template.id,
                "type": kind,
                "name": plugin_name,
                "description": template.description,
                "filters": template.filters,
                "hog": template.hog,
                "inputs": inputs,
                "enabled": True,
                "icon_url": template.icon_url,
                "inputs_schema": template.inputs_schema,
                "execution_order": plugin_config["order"],
            }

            print("Attempting to create hog function...")  # noqa: T201
            print(json.dumps(data, indent=2))  # noqa: T201

            has_addon = team.organization.is_feature_available(AvailableFeature.DATA_PIPELINES)

            if not has_addon:
                plugin_configs_without_addon.append(plugin_config["id"])

            serializer = HogFunctionSerializer(
                data=data,
                context=serializer_context,
            )
            serializer.is_valid(raise_exception=True)
            hog_functions.append(HogFunction(**serializer.validated_data))

        print(hog_functions)  # noqa: T201

        if plugin_configs_without_addon:
            print("Found plugin configs without the required addon!", plugin_configs_without_addon)  # noqa: T201

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

    legacy_plugins = (
        PluginConfig.objects.values(
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
        )
        .filter(enabled=True)
        # Order by id descending. Makes it easier to re run and quickly pick up the latest added plugins
        .order_by("-id")
    )

    if kind == "destination":
        legacy_plugins = legacy_plugins.filter(
            Q(plugin__capabilities__methods__contains=["onEvent"])
            | Q(plugin__capabilities__methods__contains=["composeWebhook"])
        )
    elif kind == "transformation":
        legacy_plugins = legacy_plugins.filter(plugin__capabilities__methods__contains=["processEvent"])
    else:
        raise ValueError(f"Invalid kind: {kind}")

    if team_ids:
        team_ids = [int(id) for id in team_ids.split(",")]
        legacy_plugins = legacy_plugins.filter(team_id__in=team_ids)

    if limit:
        legacy_plugins = legacy_plugins[:limit]

    paginator = Paginator(legacy_plugins, batch_size)
    for page_number in paginator.page_range:
        page = paginator.page(page_number)

        migrate_batch(page.object_list, kind, test_mode, dry_run)
