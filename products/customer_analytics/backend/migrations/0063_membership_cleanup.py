from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0062_custompropertyvalue_active_team_definition_index"),
    ]

    operations = [
        migrations.CreateModel(
            name="MembershipCleanupScan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("team_id", models.BigIntegerField(unique=True)),
                ("cursor", models.JSONField(default=list)),
                ("last_team_id", models.BigIntegerField(default=0)),
                ("scan_started_at", models.DateTimeField(null=True)),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="MembershipCleanupCandidate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("team_id", models.BigIntegerField()),
                ("key_hash", models.CharField(max_length=64)),
                ("group_type_index", models.PositiveSmallIntegerField()),
                ("group_key", models.TextField()),
                ("distinct_id", models.TextField()),
                (
                    "missing_side",
                    models.CharField(choices=[("person", "person"), ("group", "group")], max_length=6),
                ),
                ("first_missing_at", models.DateTimeField()),
                ("last_checked_at", models.DateTimeField()),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["team_id", "last_checked_at", "id"],
                        name="ca_membership_candidate_due",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team_id", "key_hash", "missing_side"),
                        name="ca_membership_candidate_key",
                    )
                ],
            },
        ),
    ]
