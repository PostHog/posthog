from django.db import migrations, models


class Migration(migrations.Migration):
    # help_text lives only in Django's state, so the database is left alone. A plain AlterField would
    # emit no SQL either, but it reads as a lock on posthog_user, which is read on every request.

    dependencies = [
        ("posthog", "1398_remove_userproductlist_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="user",
                    name="ui_configuration",
                    field=models.JSONField(
                        blank=True,
                        help_text="Per-user UI customization, such as SQL editor settings, shaped like the UserUIConfiguration schema. NULL means the user has no customization.",
                        null=True,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
