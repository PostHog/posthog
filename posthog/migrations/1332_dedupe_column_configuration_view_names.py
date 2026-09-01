from django.db import migrations

# Migration 0987 built both partial unique indexes with a hand-written
# `CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`. `IF NOT EXISTS` skips on a
# name collision but never checks validity, so an index left `indisvalid = false`
# by a cancelled concurrent build stayed in place, enforced nothing, and let
# duplicate view names save silently. This migration removes the conflicting
# duplicates so migration 1333 can rebuild both indexes as valid.

# Keep the most recently updated row in each conflicting group and rename the
# rest, so the unique build can succeed without losing a saved view. The suffix
# uses the full row id, which is globally unique, so two renamed rows in the same
# group cannot collide. An 8-character id prefix is not enough: `id` is a UUIDv7
# whose leading characters are only high timestamp bits, so rows created in the
# same ~65-second window share them and would be renamed to the same string.
# `left(name, 216)` leaves room for the 39-char ' (<uuid>)' suffix within the
# 255-char limit. Shared views collide per team; private views collide per
# creator. Private rows with a null `created_by_id` are excluded: Postgres treats
# nulls as distinct in a unique index, so they never conflict and must not be renamed.
DEDUPE_CONFLICTS = """
    -- migration-analyzer: safe reason=small saved-views table; only conflicting duplicate rows (rn > 1) are renamed
    WITH ranked AS (
        SELECT id,
               row_number() OVER (
                   PARTITION BY team_id, context_key, name
                   ORDER BY updated_at DESC, id DESC
               ) AS rn
        FROM posthog_columnconfiguration
        WHERE visibility = 'shared'
    )
    UPDATE posthog_columnconfiguration c
    SET name = left(c.name, 216) || ' (' || c.id::text || ')'
    FROM ranked
    WHERE c.id = ranked.id AND ranked.rn > 1;

    WITH ranked AS (
        SELECT id,
               row_number() OVER (
                   PARTITION BY team_id, context_key, name, created_by_id
                   ORDER BY updated_at DESC, id DESC
               ) AS rn
        FROM posthog_columnconfiguration
        WHERE visibility = 'private' AND created_by_id IS NOT NULL
    )
    UPDATE posthog_columnconfiguration c
    SET name = left(c.name, 216) || ' (' || c.id::text || ')'
    FROM ranked
    WHERE c.id = ranked.id AND ranked.rn > 1;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1331_messagingrecord_campaign_key_idx"),
    ]

    operations = [
        migrations.RunSQL(sql=DEDUPE_CONFLICTS, reverse_sql=migrations.RunSQL.noop),
    ]
