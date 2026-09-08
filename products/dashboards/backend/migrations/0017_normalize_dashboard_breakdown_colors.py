from django.db import migrations

# An entry pins one breakdown value to one palette slot, so it needs both keys to mean anything, and
# the slot has to be one the dashboard can resolve. Callers wrote other shapes for months because no
# write path checked: an object keyed by breakdown value, an empty object, a JSON-encoded string,
# lists of bare values, entries under other key names such as `breakdown_value` and `color`, and
# entries whose token is a CSS color.
#
# A token is a `preset-N` slot into the dashboard's color theme. `getColorFromToken` parses the N out
# and indexes the theme with it, so a hex value there yields `theme['preset-NaN']`, which is
# undefined. A null token is kept: it is the shape of a color a person cleared, and the frontend
# treats it as no color rather than as a broken one.
_USABLE_ENTRY = """
    jsonb_typeof(entry) = 'object'
    AND entry ? 'breakdownValue'
    AND entry ? 'colorToken'
    AND (
        jsonb_typeof(entry -> 'colorToken') = 'null'
        OR (entry ->> 'colorToken') ~ '^preset-[0-9]+$'
    )
"""

# One statement reads and writes each row, so a save that lands while this runs either happens before
# the row's update or waits for it. Reading the rows into Python first and writing them back would
# leave a window where a save made in between is overwritten by the value read before it.
#
# The CASE guards are load-bearing. jsonb_array_elements raises on a non-array input, and Postgres
# does not promise to evaluate the jsonb_typeof test before the EXISTS inside a plain OR, so the
# array check has to gate the expansion rather than sit beside it.
#
# WITH ORDINALITY keeps the surviving entries in their stored order. Dashboard saves diff the color
# list against what is persisted, so reordering it would show up as an unsaved change on dashboards
# this migration otherwise leaves alone.
_NORMALIZE_SQL = f"""
    UPDATE posthog_dashboard
    SET breakdown_colors = CASE
            WHEN jsonb_typeof(breakdown_colors) <> 'array' THEN '[]'::jsonb
            ELSE COALESCE(
                (
                    SELECT jsonb_agg(entry ORDER BY position)
                    FROM jsonb_array_elements(breakdown_colors) WITH ORDINALITY AS elements(entry, position)
                    WHERE {_USABLE_ENTRY}
                ),
                '[]'::jsonb
            )
        END
    WHERE breakdown_colors IS NOT NULL
      AND CASE
            WHEN jsonb_typeof(breakdown_colors) <> 'array' THEN true
            ELSE EXISTS (
                SELECT 1
                FROM jsonb_array_elements(breakdown_colors) AS entry
                WHERE NOT ({_USABLE_ENTRY})
            )
          END
"""


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0016_dashboardsavedview"),
    ]

    operations = [
        # No reverse: the dropped entries never rendered, and the original values are not
        # reconstructable from what stays.
        migrations.RunSQL(_NORMALIZE_SQL, reverse_sql=migrations.RunSQL.noop, elidable=True),
    ]
