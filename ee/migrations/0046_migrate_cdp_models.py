from django.db import migrations

MODELS_TO_MOVE = ("hook",)


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
    _move_content_types(apps, schema_editor, "ee", "cdp")


def reverse_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "cdp", "ee")


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0045_migrate_feature_flags_models"),
        ("cdp", "0001_migrate_cdp_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="Hook",
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(update_content_types, reverse_content_types),
    ]
