# Generated by Django 4.2.18 on 2025-04-08 22:17

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0706_alter_hogfunction_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="filesystem",
            name="shortcut",
            field=models.BooleanField(null=True, blank=True),
        ),
    ]
