from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1453_disable_activitylog_detail_gin_fastupdate"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="kind",
            field=models.CharField(
                choices=[("human", "Human"), ("service_account", "Service account")],
                db_default="human",
                default="human",
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(blank=True, max_length=254, null=True, unique=True, verbose_name="email address"),
        ),
        AddConstraintNotValid(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind", "human"), _negated=True) | models.Q(("email__isnull", False)),
                name="posthog_user_human_has_email",
            ),
        ),
    ]
