import json
from collections.abc import Mapping
from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction, HogFunctionType
from products.cdp.backend.models.plugin import PluginAttachment, PluginConfig

# Migrating one of these without its numeric plugin config id would reset its PluginStorage state
STORAGE_BACKED_PLUGIN_IDS = {"first-time-event-tracker"}

PLUGIN_ID_OVERRIDES = {
    "semver-flattener": "semver-flattener-plugin",
    "user-agent": "user-agent-plugin",
}


@frozen
class MigrationResult:
    created: list[int] = field(default_factory=list)
    skipped: dict[int, str] = field(default_factory=dict)


def plugin_id_from_url(url: str) -> str:
    plugin_id = url.replace("inline://", "").replace("https://github.com/PostHog/", "")
    return PLUGIN_ID_OVERRIDES.get(plugin_id, plugin_id)


def build_inputs(plugin_config: Mapping[str, Any], plugin_id: str) -> dict[str, Any]:
    inputs: dict[str, Any] = {key: {"value": value} for key, value in plugin_config["config"].items()}

    if plugin_id in STORAGE_BACKED_PLUGIN_IDS:
        inputs["legacy_plugin_config_id"] = {"value": str(plugin_config["id"])}

    if plugin_config["config"]:
        for attachment in PluginAttachment.objects.filter(plugin_config_id=plugin_config["id"]):
            contents: Any = attachment.parse_contents()
            try:
                contents = json.loads(contents)
            except Exception:
                pass
            if contents:
                inputs[attachment.key] = {"value": contents}

    return inputs


def _build_hog_function(plugin_config: Mapping[str, Any]) -> tuple[HogFunction | None, str | None]:
    url: str = plugin_config["plugin__url"] or ""

    if not url:
        return None, "plugin has no url"

    plugin_id = plugin_id_from_url(url)
    template = HogFunctionTemplate.get_template(f"plugin-{plugin_id}")

    if not template:
        return None, f"no bundled template for plugin-{plugin_id}"

    team_id = plugin_config["team_id"]

    # The consumer dedupes a plugin config against a migrated hog function by template id, so a second
    # row for the same pair would leave the outcome dependent on load order.
    if HogFunction.objects.filter(
        team_id=team_id,
        type=HogFunctionType.LEGACY_DESTINATION,
        template_id=template.template_id,
        deleted=False,
    ).exists():
        return None, "already migrated"

    inputs = build_inputs(plugin_config, plugin_id)

    # HogFunction.save() drops any key the template schema does not declare, without a trace
    schema_keys = {entry["key"] for entry in template.inputs_schema or []}
    unmapped = sorted(set(inputs) - schema_keys)
    if unmapped:
        return None, f"inputs not in the template schema: {', '.join(unmapped)}"

    return (
        HogFunction(
            team_id=team_id,
            type=HogFunctionType.LEGACY_DESTINATION,
            template_id=template.template_id,
            name=plugin_config["plugin__name"],
            description=template.description or "",
            icon_url=template.icon_url,
            hog="",
            bytecode=[],
            inputs_schema=template.inputs_schema,
            inputs=inputs,
            filters=None,
            enabled=True,
            deleted=False,
        ),
        None,
    )


def migrate_legacy_destinations(
    *,
    dry_run: bool = True,
    team_ids: list[int] | None = None,
    plugin_config_ids: list[int] | None = None,
    batch_size: int = 100,
    limit: int | None = None,
) -> MigrationResult:
    """Move enabled onEvent plugin configs onto legacy_destination hog functions running the same bundled code.

    The plugin config is left enabled. The consumer prefers the hog function for a matching template, so
    rolling back means deleting the hog function rather than restoring the plugin config.
    """
    candidates = (
        PluginConfig.objects.values("id")
        .filter(enabled=True, deleted=False, plugin__capabilities__methods__contains=["onEvent"])
        .order_by("id")
    )

    if team_ids:
        candidates = candidates.filter(team_id__in=team_ids)
    if plugin_config_ids:
        candidates = candidates.filter(id__in=plugin_config_ids)
    if limit:
        candidates = candidates[:limit]

    candidate_ids = [row["id"] for row in candidates]
    created: list[int] = []
    skipped: dict[int, str] = {}

    for start in range(0, len(candidate_ids), batch_size):
        # nosemgrep: idor-lookup-without-team (internal migration; ids come from the team-scoped query above)
        batch = PluginConfig.objects.values("id", "config", "team_id", "plugin__name", "plugin__url").filter(
            id__in=candidate_ids[start : start + batch_size]
        )

        for row in batch:
            hog_function, skip_reason = _build_hog_function(row)

            if hog_function is None:
                skipped[row["id"]] = skip_reason or "unknown"
                continue

            if not dry_run:
                # Saved one at a time rather than bulk, so each row fires the worker reload signal
                hog_function.save()

            created.append(row["id"])

    return MigrationResult(created=created, skipped=skipped)
