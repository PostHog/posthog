from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1390_rename_desktop_canvas_comment_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="deletion_scheduled_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the scheduled organization deletion will run.",
                null=True,
            ),
        ),
    ]
