"""How every backend applies an `IntegrationPatch` to the stored values of a row."""

import json
from collections.abc import Iterable, Mapping

from posthog.integrations.contracts import IntegrationPatch


def same_json(a: object, b: object) -> bool:
    # Python equality treats `1`, `1.0` and `True` as equal, but JSON stores them as different values.
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _patched(
    current: Mapping[str, object] | None, patch: Mapping[str, object], remove: Iterable[str]
) -> dict[str, object]:
    result = dict(current or {})
    result.update(patch)
    for key in remove:
        result.pop(key, None)
    return result


def changed_fields(
    *,
    config: Mapping[str, object] | None,
    sensitive_config: Mapping[str, object] | None,
    errors: str,
    patch: IntegrationPatch,
) -> dict[str, object]:
    """The new value of each field that the patch changes. An empty dict means the patch changes nothing."""
    changed: dict[str, object] = {}
    new_config = _patched(config, patch.config_patch, patch.config_remove)
    if not same_json(new_config, config or {}):
        changed["config"] = new_config
    # A secret field that cannot be decrypted reads back as a raw string, not a dict. Leave it alone
    # unless the patch touches it.
    if patch.sensitive_config_patch or patch.sensitive_config_remove:
        new_sensitive_config = _patched(sensitive_config, patch.sensitive_config_patch, patch.sensitive_config_remove)
        if not same_json(new_sensitive_config, sensitive_config or {}):
            changed["sensitive_config"] = new_sensitive_config
    if patch.errors is not None and patch.errors != errors:
        changed["errors"] = patch.errors
    return changed
