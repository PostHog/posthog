import json
from collections.abc import Mapping
from functools import partial
from typing import Any

from django.db import transaction
from django.db.models import Q

from posthog.models.team.team import Team
from posthog.plugins.site import get_site_config_from_schema
from posthog.tasks.remote_config import update_team_remote_config

from products.cdp.backend.api.hog_function import HogFunctionSerializer
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.plugin import PluginAttachment, PluginConfig, PluginSourceFile

# python manage.py migrate_plugins_to_hog_functions --dry-run --test-mode --kind=transformation

# Site apps declare no capability methods, so they are matched by repo slug
LEGACY_SITE_APP_TEMPLATES: dict[str, str] = {
    "early-access-features-app": "template-early-access-features",
    "notification-bar-app": "template-notification-bar",
    "bug-report-app": "template-hogdesk",
    "pineapple-mode-app": "template-pineapple-mode",
}

_TRUTHY_STRINGS = {"yes", "true", "1"}
_FALSY_STRINGS = {"no", "false", "0", ""}


def coerce_input_value(value: object, schema: Mapping[str, Any]) -> object:
    """Plugin configs store every value as a string, while hog function inputs are typed."""

    item_type = schema.get("type")

    if item_type == "boolean" and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUTHY_STRINGS:
            return True
        if lowered in _FALSY_STRINGS:
            return False

    if item_type == "string" and value is not None and not isinstance(value, str):
        return str(value)

    return value


def migrate_batch(legacy_plugins: Any, kind: str, test_mode: bool, dry_run: bool):
    hog_functions = []
    # A config may be disabled once something replaces it, whether that is a hog function this run
    # created or one that already existed. A config we skipped for having no template is still
    # serving the customer, so disabling it would take it away with nothing in its place.
    covered_plugin_config_ids: list[int] = []
    affected_team_ids: set[int] = set()
    # bulk_create only runs at the end of the batch, so a second config of the same app would not
    # see the row the first one produced and would create the app twice.
    covered_pairs: set[tuple[int, str]] = set()
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

            if kind == "site_app":
                template_id = LEGACY_SITE_APP_TEMPLATES.get(plugin_id)
                if not template_id:
                    print(f"Skipping plugin {plugin_name} as it has no site app template")  # noqa: T201
                    continue
            else:
                template_id = f"plugin-{plugin_id}"

            template = HogFunctionTemplate.get_template(template_id)

            if not template:
                raise Exception(f"Template not found for plugin {plugin_id}")

            schemas_by_key = {schema["key"]: schema for schema in template.inputs_schema or [] if "key" in schema}

            if kind == "site_app":
                # A site app reads what the plugin schema resolves, which fills every unset key
                config = get_site_config_from_schema(plugin_config["plugin__config_schema"], plugin_config["config"])
            else:
                config = plugin_config["config"]

            inputs = {}

            # Iterate over the plugin config to build the inputs

            for key, value in config.items():
                schema = schemas_by_key.get(key)
                inputs[key] = {"value": coerce_input_value(value, schema) if schema else value}

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

            pair = (team.id, template.template_id)
            if (
                pair in covered_pairs
                or HogFunction.objects.filter(
                    template_id=template.template_id, type=kind, team_id=team.id, enabled=True, deleted=False
                ).exists()
            ):
                print(f"Skipping plugin {plugin_name} as it already exists as a hog function")  # noqa: T201
                covered_plugin_config_ids.append(plugin_config["id"])
                affected_team_ids.add(team.id)
                continue

            data = {
                "template_id": template.template_id,
                "type": kind,
                "name": plugin_name,
                "description": template.description,
                "filters": template.filters,
                "hog": template.code,
                "inputs": inputs,
                # A test-mode site app would render on the customer's site next to the plugin it copies
                "enabled": not (test_mode and kind == "site_app"),
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
            covered_plugin_config_ids.append(plugin_config["id"])
            covered_pairs.add(pair)
            affected_team_ids.add(team.id)

        print(hog_functions)  # noqa: T201

        if not hog_functions and not covered_plugin_config_ids:
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
            # nosemgrep: idor-lookup-without-team (internal migration; IDs from prior team-scoped query)
            PluginConfig.objects.filter(id__in=covered_plugin_config_ids).update(enabled=False)

        if kind == "site_app":
            # bulk_create and queryset.update() skip the post_save receivers that rebuild the
            # team's remote config, so the browser would keep serving the old site app. Disabling a
            # config changes what is served even when this run created nothing for that team.
            for team_id in affected_team_ids:
                transaction.on_commit(partial(update_team_remote_config.delay, team_id))

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
    elif kind == "site_app":
        legacy_plugin_ids = legacy_plugin_ids.filter(
            plugin__pluginsourcefile__filename="site.ts",
            plugin__pluginsourcefile__status=PluginSourceFile.Status.TRANSPILED,
        )
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
        # nosemgrep: idor-lookup-without-team (internal migration; IDs from prior team-scoped query)
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
