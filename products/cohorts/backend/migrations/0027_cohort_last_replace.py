from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0026_cohort_population_claimed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="last_replace_marker",
            field=models.DateTimeField(
                blank=True,
                help_text="Marker of the newest replace that finished. With last_replace_floor, appends and adds ignore the rows that replace removes while its ClickHouse delete is still applying. Null if no replace has finished.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="last_replace_floor",
            field=models.DateTimeField(
                blank=True,
                help_text="Request time of the newest replace that finished. Rows before it, and the rows that replace's earlier attempts wrote, are ignored by appends and adds. Null if no replace has finished.",
                null=True,
            ),
        ),
    ]
