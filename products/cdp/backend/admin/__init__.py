# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.cdp.backend.admin import hog_function_admin, plugin_admin, plugin_config_admin  # noqa: F401
