# Conversion recommendations in Marketing analytics

Conversion recommendations scan a project's custom events and existing actions and suggest up to three business outcomes to measure.
They appear in the existing Marketing analytics Setup, under Suggestions and Conversion goals.
The `marketing-analytics-conversion-setup-ai` feature flag gates the UI, API, and MCP tools.
The existing Marketing analytics setup flag must also be enabled.

## Analysis lifecycle

The first visit to Setup starts an analysis once, after loading the saved state and checking permission to generate.
The first analysis covers 30 days; later analyses cover 14 days and require an explicit **Update recommendations** action.
Runs and completed results are stored per project, so returning to Setup does not start another analysis.
An update retains the last completed recommendations while it runs.
Interrupted runs become failed after five minutes and require an explicit retry.

Each recommendation includes its source event or action, an explanation, a proposed intent (conversion, customer, or revenue), and business questions to review.
A revenue suggestion must reference a numeric property observed in the source metadata.
A missing amount mapping downgrades the suggestion to a conversion and adds a question about the missing mapping.
Numeric metadata alone does not prove that a value is money; the user still needs to confirm units, currency, payment status, and duplicate handling.
The **Configure goals** button opens the existing goal editor.
Recommendations do not create or modify goals, and do not depend on conversion previews or the new dashboard.

## Discovery and access

Discovery reads aggregate counts for up to 20 custom events in the selected window and metadata for up to 20 existing actions.
It excludes system events, applies the project's test-account filters, and respects event/action access controls.
Action candidates retain their identity and existing filters; their volume is not evaluated during discovery.
The scan does not inspect warehouse tables or create views.

Starting analysis requires project admin access, AI data-processing consent, the feature flag, and `marketing_analytics:write` for scoped API keys.
The worker rechecks access, consent, and the flag before reading source data.
Read-only MCP sessions cannot start analysis.
The model receives aggregate evidence and source metadata, without individual event payloads or person records.
Generation uses the Go AI gateway and the production prompt and tool schema.

## API and MCP

- `GET /api/projects/:project_id/marketing_analytics/conversion_recommendations/` reads saved results and current run state.
- `POST /api/projects/:project_id/marketing_analytics/conversion_recommendations/start/` starts analysis with `{ "refresh": false }` for the first run or `{ "refresh": true }` for an explicit update.
- `marketing-analytics-conversion-recommendations` exposes the read operation in MCP.
- `marketing-analytics-start-conversion-recommendations` exposes the start operation in MCP.

Starting a run persists an analysis record and enqueues a task after the transaction commits.
Concurrent starts reuse an active run, and repeated initial requests reuse the existing run.
The start endpoint is limited to five requests per hour per user.

## Verification

Backend tests cover run reuse, refresh windows, permissions, consent, source filtering, output validation, and goal preservation.
Frontend tests cover the initial run, manual updates, polling, project isolation, and the setup feature flag.
Storybook covers analysis in progress, saved results, updates, failure, empty results, missing consent, and narrow layouts.

The standalone recommendation evaluation uses nine synthetic business cases and calls the same generator, gateway client, tool schema, and parser as production.
It does not exercise discovery queries, permissions, persistence, or Celery; those have separate tests.
A deterministic dry run checks the evaluation plumbing without calling a model:

```sh
python -m products.marketing_analytics.evals.recommendation_cards_runner --output /tmp/marketing-recommendations-dry-run.json
```

A live run requires configured Go AI gateway credentials and available model credit:

```sh
python -m products.marketing_analytics.evals.recommendation_cards_runner --live --trials 3 --output /tmp/marketing-recommendations-live.json
```

Reports record the requested and returned model, token usage, source hashes, and per-trial output.
Interrupted runs preserve completed trials.
Passing the deterministic contract checks is not a semantic quality score; live explanations and business questions still need review.
