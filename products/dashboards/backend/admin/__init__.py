# Importing these submodules fires their `@admin.register` decorators when
# `autodiscover_modules("admin")` imports this package.
from products.dashboards.backend.admin import dashboard_admin, dashboard_template_admin, text_admin  # noqa: F401
