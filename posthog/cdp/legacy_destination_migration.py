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
    dropped_inputs: dict[int, list[str]] = field(default_factory=dict)


@frozen
class _BuildOutcome:
    hog_function: HogFunction | None = None
    skip_reason: str | None = None
    dropped_inputs: list[str] = field(default_factory=list)


def plugin_id_from_url(url: str) -> str:
    plugin_id = url.replace("inline://", "").replace("https://github.com/PostHog/", "")
    return PLUGIN_ID_OVERRIDES.get(plugin_id, plugin_id)


def _as_consumer_value(value: Any) -> str:
    """Mirror how CdpLegacyEventsConsumer builds inputs from a plugin config, so a migrated row hands
    the processor exactly what it gets today. See `value?.toString() ?? ''` in that consumer."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def build_inputs(plugin_config: Mapping[str, Any], plugin_id: str) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        key: {"value": _as_consumer_value(value)} for key, value in plugin_config["config"].items()
    }

    if plugin_id in STORAGE_BACKED_PLUGIN_IDS:
        inputs["legacy_plugin_config_id"] = {"value": str(plugin_config["id"])}

    # The consumer only folds attachments in when the config is non-empty. That drops the credential
    # for a config that carries nothing else, so migrate the attachment either way.
    for attachment in PluginAttachment.objects.filter(plugin_config_id=plugin_config["id"]):
        contents: Any = attachment.parse_contents()
        try:
            contents = json.loads(contents)
        except Exception:
            pass
        if contents:
            inputs[attachment.key] = {"value": contents}

    return inputs


def _build_hog_function(plugin_config: Mapping[str, Any], drop_unmapped_inputs: bool) -> _BuildOutcome:
    url: str = plugin_config["plugin__url"] or ""

    if not url:
        return _BuildOutcome(skip_reason="plugin has no url")

    plugin_id = plugin_id_from_url(url)
    template = HogFunctionTemplate.get_template(f"plugin-{plugin_id}")

    if not template:
        return _BuildOutcome(skip_reason=f"no bundled template for plugin-{plugin_id}")

    team_id = plugin_config["team_id"]

    # The consumer dedupes a plugin config against a migrated hog function by template id, so a second
    # row for the same pair would leave the outcome dependent on load order.
    if HogFunction.objects.filter(
        team_id=team_id,
        type=HogFunctionType.LEGACY_DESTINATION,
        template_id=template.template_id,
        deleted=False,
    ).exists():
        return _BuildOutcome(skip_reason="already migrated")

    inputs = build_inputs(plugin_config, plugin_id)

    # A required input with nothing behind it saves cleanly and then fails at runtime with no credentials
    missing = sorted(
        entry["key"]
        for entry in template.inputs_schema or []
        if entry.get("required") and not inputs.get(entry["key"], {}).get("value")
    )
    if missing:
        return _BuildOutcome(skip_reason=f"required inputs with no value: {', '.join(missing)}")

    # HogFunction.save() drops any key the template schema does not declare, without a trace
    schema_keys = {entry["key"] for entry in template.inputs_schema or []}
    unmapped = sorted(set(inputs) - schema_keys)
    if unmapped and not drop_unmapped_inputs:
        return _BuildOutcome(skip_reason=f"inputs not in the template schema: {', '.join(unmapped)}")

    for key in unmapped:
        del inputs[key]

    return _BuildOutcome(
        dropped_inputs=unmapped,
        hog_function=HogFunction(
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
    )


def migrate_legacy_destinations(
    *,
    dry_run: bool = True,
    team_ids: list[int] | None = None,
    plugin_config_ids: list[int] | None = None,
    drop_unmapped_inputs: bool = True,
    batch_size: int = 100,
    limit: int | None = None,
) -> MigrationResult:
    """Move enabled onEvent plugin configs onto legacy_destination hog functions running the same bundled code.

    The plugin config is left enabled. The consumer prefers the hog function for a matching template, so
    rolling back means deleting the hog function rather than restoring the plugin config.

    Inputs the template schema does not declare are dropped, and every one is reported, because no
    bundled processor reads them. Pass drop_unmapped_inputs=False to refuse those configs instead.
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
    dropped_inputs: dict[int, list[str]] = {}

    for start in range(0, len(candidate_ids), batch_size):
        # nosemgrep: idor-lookup-without-team (internal migration; ids come from the team-scoped query above)
        batch = PluginConfig.objects.values("id", "config", "team_id", "plugin__name", "plugin__url").filter(
            id__in=candidate_ids[start : start + batch_size]
        )

        for row in batch:
            outcome = _build_hog_function(row, drop_unmapped_inputs)

            if outcome.hog_function is None:
                skipped[row["id"]] = outcome.skip_reason or "unknown"
                continue

            if outcome.dropped_inputs:
                dropped_inputs[row["id"]] = outcome.dropped_inputs

            if not dry_run:
                # Saved one at a time rather than bulk, so each row fires the worker reload signal
                outcome.hog_function.save()

            created.append(row["id"])

    return MigrationResult(created=created, skipped=skipped, dropped_inputs=dropped_inputs)


def disable_migrated_plugin_configs(
    *,
    dry_run: bool = True,
    team_ids: list[int] | None = None,
) -> list[int]:
    """Disable each enabled onEvent plugin config that a migrated hog function already covers.

    Run this only once the migrated rows are known good. Until then the plugin config stays enabled
    as the rollback: the consumer prefers the hog function, so only one of the pair ever runs, and
    deleting the hog function hands the work straight back.

    A config is left alone unless an enabled legacy_destination exists for its team and template.
    """
    candidates = PluginConfig.objects.filter(
        enabled=True, deleted=False, plugin__capabilities__methods__contains=["onEvent"]
    )
    if team_ids:
        candidates = candidates.filter(team_id__in=team_ids)

    covered_pairs = set(
        HogFunction.objects.filter(type=HogFunctionType.LEGACY_DESTINATION, enabled=True, deleted=False).values_list(
            "team_id", "template_id"
        )
    )

    to_disable = [
        row["id"]
        for row in candidates.values("id", "team_id", "plugin__url")
        if (row["team_id"], f"plugin-{plugin_id_from_url(row['plugin__url'] or '')}") in covered_pairs
    ]

    if to_disable and not dry_run:
        # nosemgrep: idor-lookup-without-team (internal migration; ids come from the team-scoped query above)
        PluginConfig.objects.filter(id__in=to_disable).update(enabled=False)

    return to_disable
