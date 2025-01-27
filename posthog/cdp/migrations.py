# Migrate from legacy plugins to new hog function plugins


import json
from posthog.api.hog_function import HogFunctionSerializer
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginAttachment, PluginConfig


def migrate_legacy_plugins(dry_run=True, team_ids=None, test_mode=False):
    # Get all legacy plugin_configs that are active with their attachments and global values
    legacy_plugins = PluginConfig.objects.select_related("plugin").filter(enabled=True)

    if team_ids:
        legacy_plugins = legacy_plugins.filter(team_id__in=team_ids)

    hog_functions = []

    for plugin_config in legacy_plugins:
        print(plugin_config.plugin.name)
        print(plugin_config.config)
        print(plugin_config.plugin.config_schema)

        plugin_id = plugin_config.plugin.url.replace("inline://", "").replace("https://github.com/PostHog/", "")

        inputs = {}
        inputs_schema = []

        # Iterate over the plugin config to build the inputs

        for schema in plugin_config.plugin.config_schema:
            if not schema.get("key"):
                continue

            print("Converting schema", schema)

            # Some hacky stuff to convert the schemas correctly
            input_schema = {
                "key": schema["key"],
                "type": schema["type"],
                "label": schema.get("name", schema["key"]),
                "description": schema.get("hint", ""),
                "secret": schema.get("secret", False),
                "required": schema.get("required", False),
                "default": schema.get("default", None),
            }

            if schema["type"] == "choice":
                input_schema["choices"] = [
                    {
                        "label": choice,
                        "value": choice,
                    }
                    for choice in schema["choices"]
                ]
                input_schema["type"] = "string"
            elif schema["type"] == "attachment":
                input_schema["type"] = "string"

            inputs_schema.append(input_schema)

        for key, value in plugin_config.config.items():
            inputs[key] = {"value": value}

        # Load all attachments for this plugin config
        attachments = PluginAttachment.objects.filter(plugin_config=plugin_config)

        for attachment in attachments:
            inputs[attachment.key] = {"value": attachment.parse_contents()}

        serializer_context = {"team": plugin_config.team, "get_team": lambda: plugin_config.team}

        data = {
            "template_id": f"plugin-{plugin_id}",
            "type": "destination",
            "name": plugin_config.plugin.name,
            "description": "This is a legacy destination migrated from our old plugin system.",
            "filters": {},
            "inputs": inputs,
            "inputs_schema": inputs_schema,
            "enabled": True,
            "icon_url": plugin_config.plugin.icon,
        }

        print("Attempting to create hog function", data)
        print(json.dumps(data, indent=2))

        serializer = HogFunctionSerializer(
            data=data,
            context=serializer_context,
        )
        serializer.is_valid(raise_exception=True)
        hog_functions.append(HogFunction(**serializer.validated_data))

    print(hog_functions)
    return hog_functions
