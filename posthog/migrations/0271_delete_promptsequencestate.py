# Generated by Django 3.2.15 on 2022-10-12 14:35

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0270_add_uploaded_media"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PromptSequenceState",
        ),
    ]
