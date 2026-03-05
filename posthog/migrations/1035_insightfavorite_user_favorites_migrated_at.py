import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1034_taggeditem_ticket_unique_constraint"),
    ]

    operations = [
        migrations.CreateModel(
            name="InsightFavorite",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "insight",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.insight",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="insightfavorite",
            constraint=models.UniqueConstraint(fields=("user", "insight"), name="posthog_unique_insightfavorited"),
        ),
        migrations.AddField(
            model_name="user",
            name="favorites_migrated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
