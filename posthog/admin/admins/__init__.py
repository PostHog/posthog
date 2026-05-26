"""Central PostHog model admin classes.

Importing this package triggers every ``@admin.register(Model)`` decorator in
``posthog/admin/admins/*.py``. ``register_all_admin()`` does ``import
posthog.admin.admins`` for that side effect; nothing else relies on the
package re-exporting names. Consumers that want a specific admin class
should import it directly from its submodule, e.g.
``from posthog.admin.admins.user_admin import UserAdmin``.

Submodules are discovered dynamically so adding a new admin file is a
one-step operation (drop the file, add the ``@admin.register`` decorator) —
no central list to keep in sync. Modules without ``@admin.register`` (e.g.
the ``*_admin.py`` files that back custom admin URLs in ``ee/urls.py``) are
still imported here, which is harmless: they only register decorators if
they have any.
"""

import pkgutil
import importlib

for _module_info in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_module_info.name}")
