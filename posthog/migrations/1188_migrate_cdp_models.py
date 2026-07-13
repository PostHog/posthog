from django.db import migrations

MODELS_TO_MOVE = (
    "hogfunction",
    "hogfunctiontemplate",
    "plugin",
    "pluginattachment",
    "pluginconfig",
    "pluginsourcefile",
    "pluginstorage",
)


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
    _move_content_types(apps, schema_editor, "posthog", "cdp")


def reverse_content_types(apps, schema_editor):
    _move_content_types(apps, schema_editor, "cdp", "posthog")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1187_migrate_hog_flow_models"),
        ("cdp", "0001_migrate_cdp_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="hogfunction",
                    name="batch_export",
                ),
                migrations.RemoveField(
                    model_name="hogfunction",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="hogfunction",
                    name="hog_function_template",
                ),
                migrations.RemoveField(
                    model_name="hogfunction",
                    name="team",
                ),
                migrations.RemoveField(
                    model_name="plugin",
                    name="has_private_access",
                ),
                migrations.RemoveField(
                    model_name="plugin",
                    name="organization",
                ),
                migrations.RemoveField(
                    model_name="pluginsourcefile",
                    name="plugin",
                ),
                migrations.RemoveField(
                    model_name="pluginconfig",
                    name="plugin",
                ),
                migrations.RemoveField(
                    model_name="pluginattachment",
                    name="plugin_config",
                ),
                migrations.RemoveField(
                    model_name="pluginattachment",
                    name="team",
                ),
                migrations.RemoveField(
                    model_name="pluginconfig",
                    name="match_action",
                ),
                migrations.RemoveField(
                    model_name="pluginconfig",
                    name="team",
                ),
                migrations.RemoveField(
                    model_name="pluginstorage",
                    name="plugin_config",
                ),
                migrations.DeleteModel(
                    name="HogFunctionTemplate",
                ),
                migrations.DeleteModel(
                    name="HogFunction",
                ),
                migrations.DeleteModel(
                    name="PluginSourceFile",
                ),
                migrations.DeleteModel(
                    name="Plugin",
                ),
                migrations.DeleteModel(
                    name="PluginAttachment",
                ),
                migrations.DeleteModel(
                    name="PluginConfig",
                ),
                migrations.DeleteModel(
                    name="PluginStorage",
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(update_content_types, reverse_content_types),
    ]
