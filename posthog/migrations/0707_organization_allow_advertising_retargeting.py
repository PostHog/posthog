# Generated by Django 4.2.18 on 2025-04-08 03:37

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0706_alter_hogfunction_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="allow_advertising_retargeting",
            field=models.BooleanField(blank=True, default=True, null=True),
        ),
    ]
