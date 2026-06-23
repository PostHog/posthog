from django.db import migrations

MODELS_TO_MOVE = ("hogflow", "hogflowtemplate")


def _move_content_types(apps, schema_editor, from_label, to_label):
    """Move ContentTypes between apps, handling duplicates idempotently."""
    db_alias = schema_editor.connection.alias
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")

    for model_name in MODELS_TO_MOVE:
        source = ContentType.objects.using(db_alias).filter(app_label=from_label, model=model_name).first()
        target = ContentType.objects.using(db_alias).filter(app_label=to_label, model=model_name).first()

        if source and target:
            Permission.objects.using(db_alias).filter(content_type=source).update(content_type=target)
            source.delete(using=db_alias)
        elif source:
            source.app_label = to_label
            source.save(using=db_alias)


def update_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "posthog", "workflows")


def reverse_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "workflows", "posthog")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1186_activitylog_ip_address"),
        ("workflows", "0007_migrate_hog_flow_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="hogflow",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="hogflow",
                    name="team",
                ),
                migrations.RemoveField(
                    model_name="hogflowtemplate",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="hogflowtemplate",
                    name="team",
                ),
                migrations.DeleteModel(
                    name="HogFlow",
                ),
                migrations.DeleteModel(
                    name="HogFlowTemplate",
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(update_content_types, reverse_content_types),
    ]
