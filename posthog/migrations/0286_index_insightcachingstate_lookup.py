# Generated by Django 3.2.16 on 2022-12-30 13:15

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "0285_capture_performance_opt_in"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- not-null-ignore
            CREATE INDEX CONCURRENTLY IF NOT EXISTS posthog_insightcachingstate_lookup ON posthog_insightcachingstate (
                last_refresh DESC NULLS LAST,
                last_refresh_queued_at DESC NULLS LAST,
                target_cache_age_seconds,
                refresh_attempt,
                team_id,
                cache_key,
                id
            )
            WHERE (target_cache_age_seconds IS NOT NULL) AND (refresh_attempt < 2)
            """,
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_insightcachingstate_lookup"',
        )
    ]
