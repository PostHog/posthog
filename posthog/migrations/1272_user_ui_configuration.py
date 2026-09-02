from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1271_add_pardot_integration_kind"),
    ]

    # Nullable with no default so existing rows stay NULL, which the frontend resolves as
    # "everything shown". New accounts get their default in UserManager.create_user instead,
    # keeping this a metadata-only ADD COLUMN on the hot posthog_user table.
    operations = [
        migrations.AddField(
            model_name="user",
            name="ui_configuration",
            field=models.JSONField(
                blank=True,
                help_text="Per-user UI customization (currently sidebar element visibility), shaped like the UserUIConfiguration schema. NULL means the user has no customization and every element shows.",
                null=True,
            ),
        ),
    ]
