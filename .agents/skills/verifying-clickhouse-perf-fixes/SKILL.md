---
name: verifying-clickhouse-perf-fixes
description: 'Use when a PostHog Code task is opening query-performance PRs from an autoresearch handoff. Measures before/after elapsed_ms for candidate SQL via the token-gated proxy endpoint and decides whether a change clears the PR threshold.'
---

# Verifying ClickHouse perf fixes

This skill gates query-performance PRs on measured improvement. It's used by
the PR-writing sandbox that follows a `mode="autoresearch_campaign"` run.

The sandbox has a `clickhouse_perf:test_read` scope on its OAuth token. All
ClickHouse queries go through `/api/query_performance_proxy/execute-test/` —
**never** connect to ClickHouse directly. The proxy is read-only (SELECT /
WITH / EXPLAIN / SHOW / DESCRIBE only, `readonly = 2` enforced server-side).

The cluster behind that endpoint is team-scoped at the ClickHouse layer
(today: it contains only team 2, "PostHog, the company"), so there is no
cross-team data to worry about leaking through the proxy.

## The measurement loop

For every candidate fix:

1. Run the **original** query through the proxy, twice, take the median
   `elapsed_ms` — this is `baseline_ms`.
2. Run the **candidate** query through the proxy, twice, take the median
   `elapsed_ms` — this is `candidate_ms`.
3. Improvement = `(baseline_ms - candidate_ms) / baseline_ms * 100`.

Reasons to double-run: ClickHouse warm vs cold cache skews the first run.
The second result is what steady-state users experience.

## Calling the proxy

```bash
POSTHOG_URL="$POSTHOG_API_URL"            # already set by the sandbox
TOKEN="$POSTHOG_PERSONAL_API_KEY"         # already set by the sandbox

curl --fail --silent --max-time 90 \
    -X POST "$POSTHOG_URL/api/query_performance_proxy/execute-test/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d @- <<EOF
{"sql": $(jq -Rs . < path/to/query.sql)}
EOF
```

Response shape:

```json
{
  "result": "...",
  "elapsed_ms": 123.4,
  "rows_read": 10000,
  "bytes_read": 1234567,
  "query_id": "..."
}
```

Store both baseline and candidate responses — the PR body should include
all four numbers: `elapsed_ms`, `rows_read`, `bytes_read`, `query_id`.

## Error cases and what they mean

| status | meaning                                           | action                                                                      |
| ------ | ------------------------------------------------- | --------------------------------------------------------------------------- |
| 400    | `sql must begin with a read-only statement`       | Only SELECT / WITH / EXPLAIN / SHOW / DESCRIBE are allowed. Rewrite.        |
| 403    | Wrong scope                                       | The token lacks `clickhouse_perf:test_read`. Check how the Task was minted. |
| 502    | `clickhouse unreachable`                          | Cluster down. Retry once, then report and move on to the next candidate.    |
| 503    | `CLICKHOUSE_PERF_TEST_HTTP_URL is not configured` | Deploy-time config is missing. Not recoverable from the sandbox — escalate. |

## The PR threshold

- **≥ 5% improvement** → open the PR ready for review.
- **< 5% improvement or regression** → open the PR as a **draft**. Include
  the measured numbers and a short analysis of why the variant missed.
  Do not skip it — a failed variant is still useful signal for the next
  campaign.

## Writing the verification script

Every PR should include a `products/query_performance_ai/verifications/<slug>.py`
script that reproduces the measurement. Keep it self-contained:

```python
#!/usr/bin/env python3
"""Perf verification for <slug>.

Reruns baseline vs candidate via the proxy and prints the comparison.
Run locally with:
    POSTHOG_URL=<url> POSTHOG_OAUTH_TOKEN=<token> python verifications/<slug>.py
"""
# ...
```

Reviewers can replay this by pointing at staging to confirm your numbers
before merging.

## Reporting back

When you're done, emit the final JSON block the handoff template asks for:

```json
{
  "prs": [{ "url": "https://github.com/PostHog/posthog/pull/NNNN", "kind": "query-rewrite", "improvement_pct": 12.3 }],
  "skipped_hunches": [{ "hunch": "materialize X as column on Y", "reason": "needs migration coordination" }]
}
```

Numbers are what the Slack post links to — so be honest about
`improvement_pct`. If you opened a draft because it missed the threshold,
report the measured value anyway (negative is fine) so the thread
explains itself.
