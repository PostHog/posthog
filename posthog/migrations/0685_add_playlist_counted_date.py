# Generated by Django 4.2.18 on 2025-03-11 20:59

from django.db import migrations, models
from django.contrib.postgres.operations import AddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0684_action_embedding_last_synced_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sessionrecordingplaylist",
            name="last_counted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        AddIndexConcurrently(
            model_name="sessionrecordingplaylist",
            index=models.Index(fields=["deleted", "last_counted_at"], name="deleted_n_last_count_idx"),
        ),
        AddIndexConcurrently(
            model_name="sessionrecordingplaylist",
            index=models.Index(fields=["deleted", "-last_modified_at"], name="deleted_n_last_mod_desc_idx"),
        ),
    ]
