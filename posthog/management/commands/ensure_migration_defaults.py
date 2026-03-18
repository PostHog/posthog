from __future__ import annotations

import importlib
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand

from posthog.models.dashboard_templates import DashboardTemplate
from posthog.models.data_color_theme import DataColorTheme

# Import the actual migration functions - single source of truth
# (using importlib because module names start with numbers)
_migration_0310 = importlib.import_module("posthog.migrations.0310_add_starter_dashboard_template")
_migration_0328 = importlib.import_module("posthog.migrations.0328_add_starter_feature_flag_template")
_migration_0537 = importlib.import_module("posthog.migrations.0537_data_color_themes")

create_product_analytics_template = _migration_0310.create_starter_template
create_feature_flag_template = _migration_0328.create_starter_template
add_default_themes = _migration_0537.add_default_themes


class Command(BaseCommand):
    help = "Ensure default data from migrations exists for schema-only restores."

    def handle(self, *args: Any, **options: Any) -> None:
        created_items: list[str] = []

        if not DataColorTheme.objects.filter(team__isnull=True, name="Default Theme").exists():
            add_default_themes(apps, None)
            created_items.append("Data color theme: Default Theme")

        if not DashboardTemplate.objects.filter(template_name="Product analytics", team__isnull=True).exists():
            create_product_analytics_template(apps, None)
            created_items.append("Dashboard template: Product analytics")

        if not DashboardTemplate.objects.filter(template_name="Flagged Feature Usage", team__isnull=True).exists():
            create_feature_flag_template(apps, None)
            created_items.append("Dashboard template: Flagged Feature Usage")

        if created_items:
            self.stdout.write("Created defaults:\n- " + "\n- ".join(created_items))
        else:
            self.stdout.write("Default migration data already present.")
