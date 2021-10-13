# Generated by Django 3.2.5 on 2021-10-13 07:00

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0178_rename_dashboard_item_to_insight"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupTypeMapping",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("group_type", models.CharField(max_length=400)),
                ("group_type_index", models.IntegerField()),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
        migrations.AddConstraint(
            model_name="grouptypemapping",
            constraint=models.UniqueConstraint(fields=("team", "group_type"), name="unique group types for team"),
        ),
        migrations.AddConstraint(
            model_name="grouptypemapping",
            constraint=models.UniqueConstraint(
                fields=("team", "group_type_index"), name="unique event column indexes for team"
            ),
        ),
        migrations.AddConstraint(
            model_name="grouptypemapping",
            constraint=models.CheckConstraint(
                check=models.Q(("group_type_index__lte", 5)), name="group_type_index is less than or equal 5"
            ),
        ),
    ]
