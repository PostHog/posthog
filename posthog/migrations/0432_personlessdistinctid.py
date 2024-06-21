# Generated by Django 4.2.11 on 2024-06-21 20:18

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0431_externaldataschema_sync_type_payload"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonlessDistinctId",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("distinct_id", models.CharField(max_length=400)),
                ("is_merged", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "team",
                    models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="personlessdistinctid",
            constraint=models.UniqueConstraint(
                fields=("team", "distinct_id"), name="unique personless distinct_id for team"
            ),
        ),
    ]
