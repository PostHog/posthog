"""Every scope's activity-log tuning, merged from the module that sits beside its model.

The per-scope modules live next to the models they tune, so the team that owns a model owns its
tuning. Each one is imported here by hand: a new scope's tuning is one import and one entry in
`MODULES`, and nothing else in the repository changes.

`posthog/models/owners.yaml` marks this file unowned on purpose. Registering a module is mechanical,
and having the activity log's owners review every product's registration would put them back in the
path of every tuning change. `posthog/test/repo_invariants/test_activity_log_config_ownership.py`
is what keeps the list honest: it fails when a module in the tree is missing from here, and when a
module and its model resolve to different teams.

Adding a scope is only ever two edits: the import above `MODULES`, and the entry in `MODULES`.
The merge below and the four exports at the bottom are shared by every scope, so leave them alone:
the repo invariant tests assume them, and a change that seems to need an edit there belongs in the
scope's own module instead.
"""

from types import ModuleType
from typing import Any

from posthog.models import oauth_activity_log_config as _oauth_activity_log_config

from products.feature_flags.backend import activity_log_config as _feature_flag_activity_log_config

# Register a scope's tuning module here. The convention for its path is `<app>.activity_log_config`;
# a config that tunes a core model sits next to that model, like the OAuth one above.
# Add your import and your entry, then stop: nothing below this tuple is edited per scope.
MODULES: tuple[ModuleType, ...] = (
    _feature_flag_activity_log_config,
    _oauth_activity_log_config,
)


def _merge(attribute: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for module in MODULES:
        for scope, value in getattr(module, attribute, {}).items():
            if scope in merged:
                raise RuntimeError(f"{attribute}: {scope} is tuned twice, in {module.__name__} and another module")
            merged[scope] = value
    return merged


FIELD_EXCLUSIONS = _merge("FIELD_EXCLUSIONS")
FIELD_NAME_OVERRIDES = _merge("FIELD_NAME_OVERRIDES")
FIELD_WITH_MASKED_CONTENTS = _merge("FIELD_WITH_MASKED_CONTENTS")
SIGNAL_EXCLUSIONS = _merge("SIGNAL_EXCLUSIONS")
