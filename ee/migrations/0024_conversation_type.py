# Generated by Django 4.2.18 on 2025-04-10 16:12

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0023_merge_20250312_0732"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="type",
            field=models.CharField(
                choices=[("assistant", "Assistant"), ("tool_call", "Tool call")], default="assistant", max_length=20
            ),
        ),
    ]
