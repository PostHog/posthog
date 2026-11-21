from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cohorts", "0024_backfill_cohort_condition_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="cohort",
            name="pending_population_mode",
            field=models.CharField(
                blank=True,
                choices=[("append", "Append"), ("replace", "Replace")],
                help_text="How the claimed static population writes its matches: append adds them to the current members, and replace also removes the members the query no longer matches. Null if the cohort was never claimed for a population.",
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="population_marker",
            field=models.DateTimeField(
                blank=True,
                help_text="ClickHouse _timestamp of the current replace attempt. Every attempt stores a newer value, and an attempt that finds a different value stored stops writing. Null when no replace is in flight.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="population_claimed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the current static population was requested. A replace keeps members added from just before this time within the clock-skew margin. Null when no population is pending.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="population_copy_started",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text="Whether the current static cohort replace has started copying its own rows into Postgres. Survives worker kills so a sweep redispatch finishes converging even if the flag is turned off.",
            ),
        ),
        migrations.AddField(
            model_name="cohort",
            name="population_first_marker",
            field=models.DateTimeField(
                blank=True,
                help_text="ClickHouse _timestamp of the first attempt in the current replace run. Kept across retries and sweep redispatches so failed-attempt cleanup deletes only this run's rows.",
                null=True,
            ),
        ),
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
                help_text="Cutoff timestamp of the newest replace that finished, set to the claim time minus the clock-skew margin and capped at the marker. Rows before it, and rows written by earlier attempts, are ignored by appends and adds. Null if no replace has finished.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="cohortcalculationhistory",
            name="mode",
            field=models.CharField(
                blank=True,
                choices=[("append", "Append"), ("replace", "Replace")],
                help_text="How this static calculation ran: append added matches to existing members, and replace also pruned non-matches. Null for dynamic cohorts or runs that recorded no mode.",
                max_length=16,
                null=True,
            ),
        ),
    ]
