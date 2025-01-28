from posthog.api.hog_function import HogFunctionSerializer
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.plugin import PluginAttachment, PluginConfig


def migrate_legacy_plugins(dry_run=True, team_ids=None, test_mode=True):
    # Get all legacy plugin_configs that are active with their attachments and global values
    legacy_plugins = PluginConfig.objects.select_related("plugin").filter(enabled=True)

    if team_ids:
        legacy_plugins = legacy_plugins.filter(team_id__in=team_ids)

    hog_functions = []

    for plugin_config in legacy_plugins:
        methods = plugin_config.plugin.capabilities.get("methods", [])

        if "onEvent" not in methods or "composeWebhook" not in methods:
            print("Skipping plugin", plugin_config.plugin.name, "as it doesn't have onEvent or composeWebhook")  # noqa: T201
            continue

        print("Attempting to migrate plugin", plugin_config)  # noqa: T201
        url: str = plugin_config.plugin.url or ""

        if not url:
            print("Skipping plugin", plugin_config.plugin.name, "as it doesn't have a url")  # noqa: T201
            continue

        plugin_id = url.replace("inline://", "").replace("https://github.com/PostHog/", "")
        plugin_name = plugin_config.plugin.name

        if test_mode:
            plugin_name = f"[CDP-TEST-HIDDEN] {plugin_name}"

        inputs = {}
        inputs_schema = []

        # Iterate over the plugin config to build the inputs

        for schema in plugin_config.plugin.config_schema:
            if not schema.get("key"):
                continue

            print("Converting schema", schema)  # noqa: T201

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

        serializer_context = {"team": plugin_config.team, "get_team": (lambda config=plugin_config: config.team)}

        data = {
            "template_id": f"plugin-{plugin_id}",
            "type": "destination",
            "name": plugin_name,
            "description": "This is a legacy destination migrated from our old plugin system.",
            "filters": {},
            "inputs": inputs,
            "inputs_schema": inputs_schema,
            "enabled": True,
            "icon_url": plugin_config.plugin.icon,
        }

        print("Attempting to create hog function...")  # noqa: T201

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
        PluginConfig.objects.filter(id__in=[plugin_config.id for plugin_config in legacy_plugins]).update(enabled=False)

    print("Done")  # noqa: T201

    return hog_functions
