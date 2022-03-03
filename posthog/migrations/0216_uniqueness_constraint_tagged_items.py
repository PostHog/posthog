# Generated by Django 3.2.5 on 2022-03-03 17:28

from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0215_add_tags_back"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY "unique_dashboard_tagged_item" ON "posthog_taggeditem" ("tag_id", "dashboard_id")
                WHERE ("insight_id" IS NULL AND "event_definition_id" IS NULL AND "property_definition_id" IS NULL AND "action_id" IS NULL);
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS
                "unique_dashboard_tagged_item";
            """,
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("insight__isnull", True),
                            ("event_definition__isnull", True),
                            ("property_definition__isnull", True),
                            ("action__isnull", True),
                        ),
                        fields=("tag", "dashboard"),
                        name="unique_dashboard_tagged_item",
                    ),
                )
            ],
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY "unique_insight_tagged_item" ON "posthog_taggeditem" ("tag_id", "insight_id")
                WHERE ("dashboard_id" IS NULL AND "event_definition_id" IS NULL AND "property_definition_id" IS NULL AND "action_id" IS NULL);
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS
                "unique_insight_tagged_item";
            """,
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("dashboard__isnull", True),
                            ("event_definition__isnull", True),
                            ("property_definition__isnull", True),
                            ("action__isnull", True),
                        ),
                        fields=("tag", "insight"),
                        name="unique_insight_tagged_item",
                    ),
                )
            ],
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY "unique_event_definition_tagged_item" ON "posthog_taggeditem" ("tag_id", "event_definition_id")
                WHERE ("dashboard_id" IS NULL AND "insight_id" IS NULL AND "property_definition_id" IS NULL AND "action_id" IS NULL);
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS
                "unique_event_definition_tagged_item"
            """,
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("dashboard__isnull", True),
                            ("insight__isnull", True),
                            ("property_definition__isnull", True),
                            ("action__isnull", True),
                        ),
                        fields=("tag", "event_definition"),
                        name="unique_event_definition_tagged_item",
                    ),
                )
            ],
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY "unique_property_definition_tagged_item" ON "posthog_taggeditem" ("tag_id", "property_definition_id")
                WHERE ("dashboard_id" IS NULL AND "insight_id" IS NULL AND "event_definition_id" IS NULL AND "action_id" IS NULL);
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS
                "unique_property_definition_tagged_item";
            """,
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("dashboard__isnull", True),
                            ("insight__isnull", True),
                            ("event_definition__isnull", True),
                            ("action__isnull", True),
                        ),
                        fields=("tag", "property_definition"),
                        name="unique_property_definition_tagged_item",
                    ),
                )
            ],
        ),
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX CONCURRENTLY "unique_action_tagged_item" ON "posthog_taggeditem" ("tag_id", "action_id")
                WHERE ("dashboard_id" IS NULL AND "insight_id" IS NULL AND "event_definition_id" IS NULL AND "property_definition_id" IS NULL);
            """,
            reverse_sql="""
                DROP INDEX CONCURRENTLY IF EXISTS
                "unique_action_tagged_item";
            """,
            state_operations=[
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(
                            ("dashboard__isnull", True),
                            ("insight__isnull", True),
                            ("event_definition__isnull", True),
                            ("property_definition__isnull", True),
                        ),
                        fields=("tag", "action"),
                        name="unique_action_tagged_item",
                    ),
                )
            ],
        ),
    ]
