# Signals report metrics

Each Signals report metric uses one bounded Trends query over event or action sources. The report derives a whole-window value and a longitudinal strip from that query.

The default query uses `date_from: "-13d"` and `interval: "day"`. This gives 14 inclusive daily buckets, including today. The strip keeps at most the trailing 14 buckets. For a longer query window, the whole-window value covers more time than the strip.

Use `affected_users` only for distinct people. It needs exactly one series with `math: "dau"`. Use `affected_sessions` only for distinct sessions. It needs exactly one series with `math: "unique_session"`. Do not use formulas or group math for either kind.

Do not author comparisons. The server does not yet keep equal adjacent comparison windows live. Stored legacy comparisons remain compatible, but list and detail responses do not expose them as live values.

Metric refresh serves snapshots measured in the last 15 minutes from the query cache. Each request runs at most 40 source series and stops on a best-effort 20-second deadline. A refresh saves `value`, `value_at`, and `series`, and clears `comparison`. The endpoint allows 10 requests per minute for each team.

Use lowercase non-currency units such as `users`, `sessions`, or `failure`. Use uppercase ISO currency codes such as `USD`.

## Access limits

Metrics with cohort references, including nested references, always hide both the query and the snapshot. This rule applies even when a token has all required scopes. `UserAccessControl` has no cohort object access policy, so the server cannot prove access. Keep this restriction until a safe cohort access policy exists. It is an intentional safety limit, not a display bug.

Unknown property-filter or resource shapes also hide the query and snapshot. Standard event, person, group, session, and element property filters are supported, subject to the access checks.
