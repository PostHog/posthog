# Marketing retention summary

Retention opens with a source table of acquired users, return rates within 7 and 30 days, and median days to a second session. Acquired users displays its count and share on one line at wider widths. View cohorts opens the existing cohort matrices on demand; Back to summary returns to the table.

## Definitions

Acquisition uses the exact selected date range and the first qualifying session. Source means normalized UTM source; referring domain remains a separate breakdown. Untagged sessions keep the existing source fallback. Only new users uses the existing 90-day lookback, with the query's existing configurable maximum of 365 days.

Each return rate divides returning users by acquired users who completed the full corresponding window. A second session must start after the first session and within the return window. Further pageviews in the first session do not count. Returns are observed up to 30 days after acquisition, capped at the current time. A dash means nobody completed the window.

Days to return is the median elapsed time to the second session among observed returners within 30 days. Recent users with incomplete windows participate in this median, so it may change as they return. The median has no improvement colors and displays a dash when no return is observed. Compare rates within a column: the 7-day and 30-day denominators can differ.

Comparison is enabled by default and can be disabled in Options. The previous acquisition period has equal duration and immediately precedes the selected period. Each period uses its own new-user lookback. Missing previous data does not produce a change indicator.

## Query and compatibility

Summary mode adds optional fields to the existing retention query and response. Callers that omit summary mode retain the cohort response. The summary materializes acquisition and per-person return results within one query, including comparison. Sources are ranked by current acquisition volume; the tail is folded before computing the median. Acquired-user shares include the folded Other row.

The existing cohort renderer and query mode remain necessary for View cohorts. Removing the old navigation entry can be considered separately while preserving saved links and query compatibility. Removing the cohort engine would also remove the drill-down.

This mode measures session returns. Conversion-goal retention is a separate behavior and needs an explicit definition before sharing these fixed-window summary metrics. Production-scale performance remains to be validated; there is no dedicated retention precompute path.
