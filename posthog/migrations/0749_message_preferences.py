from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0748_update_featureflag_super_groups"),  # Based on the last migration seen in the directory
    ]

    operations = [
        migrations.CreateModel(
            name="MessageCategory",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField(blank=True)),
                (
                    "is_system_category",
                    models.BooleanField(default=False, help_text="System categories cannot be deleted"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name_plural": "message categories",
            },
        ),
        migrations.CreateModel(
            name="RecipientIdentifier",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("identifier", models.CharField(max_length=512)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("email", "Email Address"),
                            ("phone", "Phone Number"),
                            ("device", "Device ID"),
                            ("push", "Push Token"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "unique_together": {("identifier", "type")},
            },
        ),
        migrations.CreateModel(
            name="MessagePreference",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opted_in", models.BooleanField(help_text="Null means no explicit preference set", null=True)),
                ("last_updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preferences",
                        to="posthog.messagecategory",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="preferences",
                        to="posthog.recipientidentifier",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="User who last updated this preference",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="posthog.user",
                    ),
                ),
            ],
            options={
                "unique_together": {("recipient", "category")},
            },
        ),
        migrations.AddIndex(
            model_name="recipientidentifier",
            index=models.Index(fields=["identifier", "type"], name="posthog_rec_identif_e8c0d6_idx"),
        ),
        migrations.AddIndex(
            model_name="recipientidentifier",
            index=models.Index(fields=["type"], name="posthog_rec_type_858382_idx"),
        ),
        migrations.AddIndex(
            model_name="messagepreference",
            index=models.Index(fields=["recipient", "category"], name="posthog_mes_recipie_a123b4_idx"),
        ),
        migrations.AddIndex(
            model_name="messagepreference",
            index=models.Index(fields=["category"], name="posthog_mes_categor_456d89_idx"),
        ),
        migrations.AddIndex(
            model_name="messagepreference",
            index=models.Index(fields=["opted_in"], name="posthog_mes_opted_i_789e0f_idx"),
        ),
    ]
