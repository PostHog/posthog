# Signals report metrics

Each Signals report metric uses one bounded Trends query over event or action sources. The report derives a whole-window value and a longitudinal strip from that query.

The default query uses `date_from: "-13d"` and `interval: "day"`. This gives 14 inclusive daily buckets, including today. The strip keeps at most the trailing 14 buckets. For a longer query window, the whole-window value covers more time than the strip.

Use `affected_users` only for distinct people. It needs exactly one series with `math: "dau"`. Use `affected_sessions` only for distinct sessions. It needs exactly one series with `math: "unique_session"`. Do not use formulas or group math for either kind.

Do not author comparisons. The server does not yet keep equal adjacent comparison windows live. Stored legacy comparisons remain compatible, but list and detail responses do not expose them as live values.

An actionable report summary includes an Expected impact section after its Solution section. The section uses a queried baseline to estimate the metric's post-fix value or range and its delta. This forecast stays in prose because it is an estimate, not a live report metric or comparison. If the solution does not directly change the observed metric, the summary names the measurement needed to verify the solution. If the evidence has no usable baseline or denominator, the summary states that it cannot make a credible estimate.

Metric refresh serves snapshots measured in the last 15 minutes from the query cache. Each request runs at most 40 source series and stops on a best-effort 20-second deadline. A refresh saves `value`, `value_at`, and `series`, and clears `comparison`. The endpoint allows 10 requests per minute for each team.

Use lowercase non-currency units such as `users`, `sessions`, or `failure`. Use uppercase ISO currency codes such as `USD`.

Every write path reads the organization-level `signals-report-metrics` flag through `report_content_gates.py`. The agentic research pipeline and the scout `emit_report` / `edit_report` channel both drop authored metrics while the flag is off, because a stored definition is also a query that the refresh path runs later. The check fails closed, so a flag-service error stores no definitions. A scout that sends an empty list still clears the report's metrics.

## Access limits

Metrics with cohort references, including nested references, always hide both the query and the snapshot. This rule applies even when a token has all required scopes. `UserAccessControl` has no cohort object access policy, so the server cannot prove access. Keep this restriction until a safe cohort access policy exists. It is an intentional safety limit, not a display bug.

Unknown property-filter or resource shapes also hide the query and snapshot. Standard event, person, group, session, and element property filters are supported, subject to the access checks.
