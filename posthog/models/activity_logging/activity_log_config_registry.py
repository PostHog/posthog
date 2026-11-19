"""Every scope's activity-log tuning module, listed for the merge in `activity_log.py`.

The per-scope modules live next to the models they tune (`activity_log_config.py`), so the team that
owns a model owns its tuning. This file holds only the imports and `MODULES`: the merge and its
duplicate check live in `activity_log.py`, so a change to that logic is reviewed.

`posthog.models` imports `activity_log.py` to register `ActivityLog` during `django.setup()`.
Merging at import keeps the exported dictionaries complete for diffing, masking, and signal
handlers in both web and worker processes. Keep the imported config modules data only.

`posthog/models/owners.yaml` marks this file unowned on purpose. Registering a module is mechanical,
and having the activity log's owners review every product's registration would put them back in the
path of every tuning change. `posthog/test/repo_invariants/test_activity_log_config_ownership.py`
keeps the list honest: it fails when a module in the tree is missing from here, and when a module
and its model resolve to different teams. It also rejects logic in this unowned file.

Adding a scope is only ever two edits: the import above `MODULES`, and the entry in `MODULES`.
"""

from types import ModuleType

from posthog.models import oauth_activity_log_config as _oauth_activity_log_config

from products.feature_flags.backend import activity_log_config as _feature_flag_activity_log_config

# Add your import above and your module below, then stop.
MODULES: tuple[ModuleType, ...] = (
    _feature_flag_activity_log_config,
    _oauth_activity_log_config,
)
