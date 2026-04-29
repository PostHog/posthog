import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1089_ducklake_backfill_populate"),
        ("posthog", "1125_scheduledchange_timezone"),
    ]

    operations = [
        migrations.AlterField(
            model_name="duckgresserver",
            name="team",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="duckgres_server",
                to="posthog.team",
            ),
        ),
        migrations.AlterField(
            model_name="ducklakecatalog",
            name="team",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ducklake_catalog",
                to="posthog.team",
            ),
        ),
        migrations.AlterField(
            model_name="ducklakecatalog",
            name="organization",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="ducklake_catalog",
                to="posthog.organization",
            ),
        ),
        migrations.AlterField(
            model_name="duckgresserver",
            name="organization",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="duckgres_server",
                to="posthog.organization",
            ),
        ),
    ]
