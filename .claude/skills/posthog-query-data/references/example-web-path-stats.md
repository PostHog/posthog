# Web path stats

In this view you can validate all of the paths that were accessed in your application, regardless of when they were accessed through the lifetime of a user session.

The bounce rate indicates the percentage of users who left your page immediately after visiting without capturing any event.

```sql
SELECT
    nullIf(pathname, '') AS `context.columns.breakdown_value`,
    tuple(uniqMergeIf(web_pre_aggregated_stats.persons_uniq_state, and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), uniqMergeIf(web_pre_aggregated_stats.persons_uniq_state, and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.visitors`,
    tuple(sumMergeIf(web_pre_aggregated_stats.pageviews_count_state, and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), sumMergeIf(web_pre_aggregated_stats.pageviews_count_state, and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.views`,
    any(bounces.`context.columns.bounce_rate`) AS `context.columns.bounce_rate`,
    divide(`context.columns.visitors`.1, sum(`context.columns.visitors`.1) OVER ()) AS `context.columns.ui_fill_fraction`
FROM
    web_pre_aggregated_stats
    LEFT JOIN (SELECT
        nullIf(entry_pathname, '') AS `context.columns.breakdown_value`,
        tuple(uniqMergeIf(persons_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), uniqMergeIf(persons_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.visitors`,
        tuple(sumMergeIf(pageviews_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), sumMergeIf(pageviews_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999'))))) AS `context.columns.views`,
        tuple(divide(sumMergeIf(bounces_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), nullif(uniqMergeIf(sessions_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-21 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-29 07:59:59.999999')))), 0)), divide(sumMergeIf(bounces_count_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999')))), nullif(uniqMergeIf(sessions_uniq_state, and(greaterOrEquals(period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(period_bucket, toDateTime('2026-01-22 07:59:59.999999')))), 0))) AS `context.columns.bounce_rate`
    FROM
        web_pre_aggregated_bounces
    WHERE
        and(and(greaterOrEquals(web_pre_aggregated_bounces.period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(web_pre_aggregated_bounces.period_bucket, toDateTime('2026-01-29 07:59:59.999999'))), notEquals(nullIf(entry_pathname, ''), NULL))
    GROUP BY
        `context.columns.breakdown_value`) AS bounces ON equals(web_pre_aggregated_stats.pathname, bounces.`context.columns.breakdown_value`)
WHERE
    and(and(greaterOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-14 08:00:00.000000')), lessOrEquals(web_pre_aggregated_stats.period_bucket, toDateTime('2026-01-29 07:59:59.999999'))), notEquals(nullIf(pathname, ''), NULL))
GROUP BY
    `context.columns.breakdown_value`
ORDER BY
    `context.columns.visitors` DESC
LIMIT 11
OFFSET 0
```
