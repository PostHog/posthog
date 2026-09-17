# Marketing retention summary

Retention opens with a source table of users, return rates within 7 and 30 days, and median days to a second session. The volume column is labeled New users when Only new users is enabled and Users otherwise. It displays its count and share on one line at wider widths. The interface exposes only the summary. The legacy cohort frontend is removed.

## Definitions

Acquisition uses the exact selected date range and the first qualifying session. Retention defaults to the last 30 days and offers presets up to 90 days. The backend rejects longer summary ranges. Source means normalized UTM source; referring domain remains a separate breakdown. Untagged sessions keep the existing source fallback. Only new users uses the existing 90-day lookback, with the query's existing configurable maximum of 365 days.

Each return rate divides returning users by acquired users who completed the full corresponding window. A second session must start after the first session and within the return window. Further pageviews in the first session do not count. Returns are observed up to 30 days after acquisition, capped at the current time. A dash means nobody completed the window.

Days to return is the estimated median elapsed time to the second session among observed returners within 30 days. Recent users with incomplete windows participate in this median, so it may change as they return. The median uses the shared comparison arrow and tooltip, with neutral colors and displays a dash when no return is observed. Compare rates within a column: the 7-day and 30-day denominators can differ.

Comparison is enabled by default and can be disabled with the comparison selector in the toolbar. The previous acquisition period uses the shared date comparison rules, including relative ranges and calendar periods. Each period uses its own new-user lookback. Missing previous data does not produce a change indicator.

## Query and compatibility

Summary mode adds optional fields to the existing retention query and response. Callers that omit summary mode retain the cohort response. The summary materializes acquisition and per-person return results within one query, including comparison. Return events are joined to each acquisition window before aggregation, and the median uses ClickHouse's bounded reservoir. The table defaults to current acquisition volume, and sources are selected by that volume; the tail is folded before computing the median. User shares include the folded Other row.

The legacy cohort renderer, summary helpers, and frontend controls are removed. The backend cohort query mode remains compatible with existing callers. This cleanup is a separate draft and must be reviewed independently before merging.

This mode measures session returns. Conversion-goal retention is a separate behavior and needs an explicit definition before sharing these fixed-window summary metrics. There is no dedicated retention precompute path.
