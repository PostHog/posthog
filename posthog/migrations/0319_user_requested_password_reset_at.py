# Generated by Django 3.2.18 on 2023-06-05 17:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0318_alter_earlyaccessfeature_stage"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="requested_password_reset_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
