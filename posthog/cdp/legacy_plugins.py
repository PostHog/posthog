from typing import Optional

from posthog.api.hog_function import HogFunctionSerializer
from posthog.api.hog_function_template import HogFunctionTemplates


def hog_function_from_plugin_config(plugin_config: dict, serializer_context: dict) -> Optional[HogFunctionSerializer]:
    plugin = plugin_config["plugin"]
    # Attempts to find a related HogFunctionTemplate for the plugin config

    plugin_id = plugin.url.replace("inline://", "").replace("https://github.com/PostHog/", "")

    # Inline plugins are named slightly differently so we fix it here
    if plugin_id == "semver-flattener":
        plugin_id = "semver-flattener-plugin"
    if plugin_id == "user-agent":
        plugin_id = "user-agent-plugin"

    template = HogFunctionTemplates.template(f"plugin-{plugin_id}")

    if not template:
        raise Exception(f"Template not found for plugin {plugin_id}")

    inputs = {}
    for key, value in plugin_config["config"].items():
        inputs[key] = {"value": value}

    data = {
        "template_id": template.id,
        "type": template.type,
        "name": plugin.name,
        "description": template.description,
        "filters": template.filters,
        "hog": template.hog,
        "inputs": inputs,
        "enabled": True,
        "icon_url": template.icon_url,
        "inputs_schema": template.inputs_schema,
        "execution_order": plugin_config["order"],
        "created_by": serializer_context["request"].user,
    }

    serializer = HogFunctionSerializer(
        data=data,
        context=serializer_context,
    )

    serializer.is_valid(raise_exception=True)
    return serializer
