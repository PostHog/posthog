from django.db import migrations, models


def share_existing_keys(apps, schema_editor):
    # Every key before this migration was added under the admin-only rule, so all of them stay usable by everyone.
    LLMProviderKey = apps.get_model("ai_observability", "LLMProviderKey")
    LLMProviderKey.objects.using(schema_editor.connection.alias).update(shared=True)


class Migration(migrations.Migration):
    dependencies = [
        ("ai_observability", "0098_retire_evaluation_config"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmproviderkey",
            name="shared",
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(share_existing_keys, migrations.RunPython.noop, elidable=True),
    ]
