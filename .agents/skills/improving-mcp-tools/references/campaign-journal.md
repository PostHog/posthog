# Campaign journal and PR evidence format

The journal is the campaign's memory. It lives wherever the campaign runner
persists state (a task artefact, a repo-side `campaign-journal.md` on the
campaign branch, or the operator's chosen store) — the format is what matters,
because a later iteration or a different agent must be able to resume from it
without repeating attempted work.

## Iteration record

Append one block per iteration, including discarded ones:

```markdown
## Iteration 7 — 2026-07-02T14:05Z

issue: execute-sql schema confusion — agents pass `sql` instead of `query` (reach: 86k failed calls/30d)
source: query-mcp-tool-failures + benchmark task sql-daily-event-volume
attempt: clarified input description in products/data_warehouse/mcp/tools.yaml (execute-sql.query)
baseline: probes 24/26 ok, p95 2100ms; agent-mode task success 19/27, tool-selection 22/27
after: probes 26/26 ok, p95 2050ms; agent-mode task success 22/27, tool-selection 25/27
verdict: KEEP → PR #67991 (stamphog)
```

Discarded example:

```markdown
## Iteration 8 — 2026-07-02T15:12Z

issue: query-funnel discoverability for "conversion" intents
attempt: description rewrite emphasizing conversion phrasing
after: tool-selection unchanged (22/27), task success -1
verdict: DISCARD (no improvement; attempt 1 of 2)
```

## Parked issues

Maintain a `parked` list at the top of the journal: issue key + why (two
failed attempts, needs handler code, needs human decision). Never re-pick a
parked issue.

## PR evidence block

Every campaign PR body must contain this section, verbatim numbers from the
harness:

```markdown
## Eval evidence

- Benchmark: v0 (27 tasks), harness at <commit>
- Baseline: `<exact command>` → probes 24/26 ok, p95 2100ms, task success 19/27
- After: same command → probes 26/26 ok, p95 2050ms, task success 22/27
- No-regression sample: tasks <ids>, unchanged
- Journal: iteration 7
```

A PR without this block is not a campaign PR and must not carry the campaign
label.
