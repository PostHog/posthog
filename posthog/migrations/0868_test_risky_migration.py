import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0867_add_updated_at_to_feature_flags"),
    ]

    operations = [
        # Policy violation: Using AutoField instead of UUID
        migrations.CreateModel(
            name="TestBadModel",
            fields=[
                ("id", models.AutoField(primary_key=True)),
                ("name", models.CharField(max_length=255)),
            ],
        ),
        # High risk: NOT NULL without default (locks table)
        migrations.AddField(
            model_name="team",
            name="test_risky_field",
            field=models.CharField(max_length=255, null=False, default=""),
        ),
        # High risk: Volatile default (table rewrite)
        migrations.AddField(
            model_name="team",
            name="test_uuid_field",
            field=models.UUIDField(default=uuid.uuid4, null=False),
        ),
        # High risk: Non-concurrent index
        migrations.AddIndex(
            model_name="team",
            index=models.Index(fields=["test_risky_field"], name="test_risky_idx"),
        ),
        # Critical: DML mixed with schema changes
        migrations.RunSQL(
            sql="UPDATE posthog_team SET test_risky_field = 'test' WHERE test_risky_field = ''",
        ),
        # Blocked: Renaming field
        migrations.RenameField(
            model_name="team",
            old_name="test_risky_field",
            new_name="test_renamed_field",
        ),
    ]
