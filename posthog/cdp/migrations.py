import json
from typing import Any
from posthog.api.hog_function import HogFunctionSerializer
from posthog.constants import AvailableFeature
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginAttachment, PluginConfig
from posthog.models.team.team import Team
from django.db.models import Q

# python manage.py migrate_plugins_to_hog_functions --dry-run --test-mode


def migrate_legacy_plugins(dry_run=True, team_ids=None, test_mode=True, kind=str):
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
        .order_by("order")
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
        legacy_plugins = legacy_plugins.filter(team_id__in=team_ids)

    teams = Team.objects.filter(id__in=legacy_plugins.values_list("team_id", flat=True).distinct())
    teams_by_id = {team.id: team for team in teams}

    hog_functions = []
    plugin_configs_without_addon = []

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

        if test_mode:
            plugin_name = f"[CDP-TEST-HIDDEN] {plugin_name}"

        inputs = {}
        inputs_schema = []

        # Iterate over the plugin config to build the inputs

        for schema in plugin_config["plugin__config_schema"]:
            if not schema.get("key"):
                continue

            print("Converting schema", schema)  # noqa: T201

            # Some hacky stuff to convert the schemas correctly
            input_schema = {
                "key": schema["key"],
                "type": schema["type"],
                "label": schema.get("name", schema["key"]),
                "secret": schema.get("secret", False),
                "required": schema.get("required", False),
                "templating": False,
            }

            if schema.get("default"):
                input_schema["default"] = schema["default"]

            if schema.get("hint"):
                input_schema["description"] = schema["hint"]

            if schema["type"] == "choice":
                input_schema["choices"] = [
                    {
                        "label": choice,
                        "value": choice,
                    }
                    for choice in schema["choices"]
                ]
            elif schema["type"] == "attachment":
                input_schema["secret"] = schema["key"] == "googleCloudKeyJson"
                input_schema["type"] = "json"

            inputs_schema.append(input_schema)

        for key, value in plugin_config["config"].items():
            inputs[key] = {"value": value}

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

        team = teams_by_id[plugin_config["team_id"]]
        serializer_context = {"team": team, "get_team": (lambda t=team: t)}

        icon_url = (
            plugin_config["plugin__icon"] or f"https://raw.githubusercontent.com/PostHog/{plugin_id}/main/logo.png"
        )

        data = {
            "template_id": f"plugin-{plugin_id}",
            "type": kind,
            "name": plugin_name,
            "description": "This is a legacy destination migrated from our old plugin system.",
            "filters": {},
            "inputs": inputs,
            "inputs_schema": inputs_schema,
            "enabled": True,
            "hog": "return event",
            "icon_url": icon_url,
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
