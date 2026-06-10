# Generated manually for dashboard widget entity

from django.db import migrations, models

import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0008_dashboardtile_widget_id"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="dashboardtile",
                    name="dash_tile_exactly_one_related_object",
                ),
                migrations.AddConstraint(
                    model_name="dashboardtile",
                    constraint=models.CheckConstraint(
                        condition=posthog.models.utils.build_unique_relationship_check(
                            ("insight", "text", "button_tile", "widget")
                        ),
                        name="dash_tile_exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_dashboardtile" DROP CONSTRAINT IF EXISTS "dash_tile_exactly_one_related_object";
                        ALTER TABLE "posthog_dashboardtile" ADD CONSTRAINT "dash_tile_exactly_one_related_object" -- existing-table-constraint-ignore
                        CHECK (
                            ("insight_id" IS NOT NULL AND "text_id" IS NULL AND "button_tile_id" IS NULL AND "widget_id" IS NULL)
                            OR ("insight_id" IS NULL AND "text_id" IS NOT NULL AND "button_tile_id" IS NULL AND "widget_id" IS NULL)
                            OR ("insight_id" IS NULL AND "text_id" IS NULL AND "button_tile_id" IS NOT NULL AND "widget_id" IS NULL)
                            OR ("insight_id" IS NULL AND "text_id" IS NULL AND "button_tile_id" IS NULL AND "widget_id" IS NOT NULL)
                        )
                        NOT VALID;
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_dashboardtile" DROP CONSTRAINT IF EXISTS "dash_tile_exactly_one_related_object";
                        ALTER TABLE "posthog_dashboardtile" ADD CONSTRAINT "dash_tile_exactly_one_related_object" -- existing-table-constraint-ignore
                        CHECK (
                            ("insight_id" IS NOT NULL AND "text_id" IS NULL AND "button_tile_id" IS NULL)
                            OR ("insight_id" IS NULL AND "text_id" IS NOT NULL AND "button_tile_id" IS NULL)
                            OR ("insight_id" IS NULL AND "text_id" IS NULL AND "button_tile_id" IS NOT NULL)
                        )
                        NOT VALID;
                    """,
                ),
            ],
        ),
    ]
