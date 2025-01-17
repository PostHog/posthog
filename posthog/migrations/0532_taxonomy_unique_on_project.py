# Generated by Django 4.2.15 on 2024-12-09 15:51

from django.db import migrations
from django.db import models
import django.db.models.functions.comparison
import posthog.models.utils
from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Added to support concurrent index creation
    dependencies = [("posthog", "0531_alter_hogfunction_type")]

    operations = [
        # First clean up rows that would fail the project-based unique constraints we're adding
        migrations.RunSQL(
            sql="""
            DELETE FROM posthog_propertydefinition
            WHERE team_id IN (
                SELECT id FROM posthog_team WHERE id != project_id
            );""",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.RunSQL(
            sql="""
            DELETE FROM posthog_eventdefinition
            WHERE team_id IN (
                SELECT id FROM posthog_team WHERE id != project_id
            );""",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        migrations.RunSQL(
            sql="""
            DELETE FROM posthog_eventproperty
            WHERE team_id IN (
                SELECT id FROM posthog_team WHERE id != project_id
            );""",
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        ),
        # Remove misguided `project_id`-only indexes from the previous migration
        RemoveIndexConcurrently(
            model_name="eventproperty",
            name="posthog_eve_proj_id_22de03_idx",
        ),
        RemoveIndexConcurrently(
            model_name="eventproperty",
            name="posthog_eve_proj_id_26dbfb_idx",
        ),
        RemoveIndexConcurrently(
            model_name="propertydefinition",
            name="index_property_def_query_proj",
        ),
        RemoveIndexConcurrently(
            model_name="propertydefinition",
            name="posthog_pro_project_3583d2_idx",
        ),
        # Add new useful indexes using `coalesce(project_id, team_id)`
        AddIndexConcurrently(
            model_name="eventproperty",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(models.F("project_id"), models.F("team_id")),
                models.F("event"),
                name="posthog_eve_proj_id_22de03_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="eventproperty",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(models.F("project_id"), models.F("team_id")),
                models.F("property"),
                name="posthog_eve_proj_id_26dbfb_idx",
            ),
        ),
        AddIndexConcurrently(
            model_name="propertydefinition",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(models.F("project_id"), models.F("team_id")),
                models.F("type"),
                django.db.models.functions.comparison.Coalesce(models.F("group_type_index"), -1),
                models.OrderBy(models.F("query_usage_30_day"), descending=True, nulls_last=True),
                models.OrderBy(models.F("name")),
                name="index_property_def_query_proj",
            ),
        ),
        AddIndexConcurrently(
            model_name="propertydefinition",
            index=models.Index(
                django.db.models.functions.comparison.Coalesce(models.F("project_id"), models.F("team_id")),
                models.F("type"),
                models.F("is_numerical"),
                name="posthog_pro_project_3583d2_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="eventdefinition",
            constraint=posthog.models.utils.UniqueConstraintByExpression(
                concurrently=True, expression="(coalesce(project_id, team_id), name)", name="event_definition_proj_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="eventproperty",
            constraint=posthog.models.utils.UniqueConstraintByExpression(
                concurrently=True,
                expression="(coalesce(project_id, team_id), event, property)",
                name="posthog_event_property_unique_proj_event_property",
            ),
        ),
        migrations.AddConstraint(
            model_name="propertydefinition",
            constraint=posthog.models.utils.UniqueConstraintByExpression(
                concurrently=True,
                expression="(coalesce(project_id, team_id), name, type, coalesce(group_type_index, -1))",
                name="posthog_propdef_proj_uniq",
            ),
        ),
    ]
