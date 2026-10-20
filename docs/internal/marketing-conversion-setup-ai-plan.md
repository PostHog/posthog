# Conversion recommendations in Marketing analytics

Conversion recommendations scan a project's custom events and existing actions and suggest up to three business outcomes to measure.
They appear in the existing Marketing analytics Setup, under Suggestions and Conversion goals.
With source onboarding enabled, the dashboard also shows the same conversion recommendations beside source setup.
Dashboard suggestions have a dismiss button in their header when the Setup tab is available.
Source onboarding, source loading failures, and connection diagnostics stay visible even when source suggestions have been dismissed.
Dismiss hides the whole block for that user and project in the current browser and opens a dialog linking to the relevant Setup section.
Setup keeps the sources and conversion recommendations available, with **Show suggestions on dashboard** to restore a hidden block.
The `marketing-analytics-conversion-setup-ai` feature flag gates the UI, API, and MCP tools.
The existing Marketing analytics setup flag must also be enabled.

## Analysis lifecycle

The first visit to Setup or the source onboarding dashboard starts an analysis once, after loading the saved state and checking permission to generate.
Analyses cover 30 days until one completes successfully; later analyses cover 14 days and require an explicit **Scan again** action.
Runs and completed results are stored per project, so returning to Setup does not start another analysis.
After a successful scan, a project waits one hour from its completion before starting another scan.
Failed scans can be retried immediately with **Scan again**, including after an interrupted run expires.
An active scan is reused instead of starting another in parallel.
The backend enforces this interval for UI and MCP requests and returns the existing run during the cooldown.
The UI updates the countdown when it receives scan status, so a newly completed scan shows 60 minutes.
It enables **Scan again** when the hour has passed and never starts a scheduled rescan.
An update retains the last completed recommendations while it runs.
Interrupted runs become failed after five minutes and require an explicit retry.

Recommendations appear as compact rows in a single panel.
Each row shows its source event or action, proposed intent (conversion, customer, or revenue), and a **Review suggestion** action.
Expanding the row shows the explanation, amount property, and up to two actionable checks specific to the proposed goal.
Count-only suggestions do not ask about revenue units, currency, or hypothetical revenue upgrades.
Each row has **Dismiss**. Dismissed source references and names persist per user and project in the current browser and stay hidden across scans.
**Dismissed suggestions** lists those sources and provides **Restore**.
Restoring makes a source eligible to appear again; it appears immediately when the latest scan still recommends it and no goal for that event or action is configured.
Earlier suggestions remain listed after a scan, without treating their old evidence as current results.
**Scan details** contains the analysis period and discovery limits.
**Scan again** scans recent events and actions and generates updated suggestions.
A revenue suggestion must reference a numeric property observed in the source metadata.
A missing amount mapping downgrades the suggestion to a conversion and adds a question about the missing mapping.
Numeric metadata alone does not prove that a value is money; the user still needs to confirm units, currency, payment status, and duplicate handling.
The **Configure goals** button opens the existing goal editor, scrolls it into view, and focuses the name field, including when the Conversion goals section is already open.
It preserves any draft already in the editor.
Recommendations do not automatically create or modify goals, and do not depend on conversion previews or the new dashboard.
In Setup, **Review suggestion** opens the existing goal editor with the proposed name and event or action.
Revenue suggestions select the sum of the proposed amount property; customer suggestions select the customer flag.
Business questions remain visible for review, and nothing is saved until the user clicks **Add conversion goal**.
The form blocks duplicate submissions and keeps the draft after a failed save so the user can retry.
Recommendations for an event or action with a saved goal are hidden from the pending list, even if the user changed the name, measurement, filters, or revenue and customer flags before saving.
Opening a stale suggestion reviews a goal for that source, preferring an exact measurement match when there are several.
Manual goals still use full measurement equivalence to prevent duplicate saves while allowing distinct filtered goals for the same source.
The list updates after a successful save, without another AI analysis.
If no suggestions remain to review, the recommendation block disappears from the dashboard after a successful scan, including when all are configured or dismissed.
Setup shows a compact confirmation and keeps **Scan again** available after the cooldown; saved goals remain in the configured goals list.
A failed refresh explains that the latest attempt failed while the saved goals and last successful results remain available.
An active scan or a failed request remains visible on the dashboard so its status and retry action are available.
Deleting the last goal for a source makes its suggestion available again.
The form also checks for an equivalent saved goal before submitting, including when settings changed after the draft opened.
The setup plan no longer generates rules that suggest creating conversion goals or enabling Revenue or Customer.
The backend removes those suggestions for both the UI and the setup plan's MCP tool, and stops running the event-ranking scan that supplied them.
Misconfigured goal warnings and integration diagnostics remain available.
Without AI recommendations enabled, users configure goals manually; capability readiness still explains missing revenue or customer definitions.

## Discovery and access

Discovery reads aggregate counts for up to 20 custom events in the selected window and metadata for up to 20 existing actions.
It excludes system events, applies the project's test-account filters, and respects event/action access controls.
Action candidates retain their identity and existing filters; their volume is not evaluated during discovery.
The scan does not inspect warehouse tables or create views.

Starting analysis requires project admin access, AI data-processing consent, the feature flag, and `marketing_analytics:write` for scoped API keys.
The worker rechecks access, consent, and the flag before reading source data.
Read-only MCP sessions cannot start analysis.
Runs belong to the requested environment, matching its events and configured goals.
Discovery, goal context, locking, and generation permissions use that same environment; parent and child scans remain separate.
The model receives aggregate evidence, source metadata, and summaries of existing goals, including goals absent from the recent candidate catalog.
Summaries include source identity, name, measurement, revenue/customer flags, and whether filters apply; they omit filter values, individual event payloads, and person records.
Configured action summaries respect action access controls.
Selection prioritizes distinct business outcomes not already measured, and can return no suggestions when only weaker steps from an already measured journey remain.
The backend also drops suggestions for sources marked as already configured.
Generation uses the Go AI gateway and the production prompt and tool schema.
When the organization enables AI privacy mode, the request includes the gateway privacy header so prompts and responses are not recorded in AI telemetry.
The synthetic evaluation runner always requests that privacy mode.

## API and MCP

- `GET /api/projects/:project_id/marketing_analytics/conversion_recommendations/` reads saved results and current run state.
- `POST /api/projects/:project_id/marketing_analytics/conversion_recommendations/start/` starts analysis with `{ "refresh": false }` for the first run or `{ "refresh": true }` for an explicit update.
- `marketing-analytics-conversion-recommendations` exposes the read operation in MCP.
- `marketing-analytics-start-conversion-recommendations` exposes the start operation in MCP only after the organization approves AI data processing.
  Reading saved recommendations does not require new AI processing consent; the backend still enforces access and the feature flag.

Starting a run persists an analysis record and enqueues a task after the transaction commits.
Concurrent starts reuse an active run, and repeated initial requests reuse the existing run.
The start endpoint is limited to five requests per hour per user.

## Verification

The static IDOR coverage check verifies that recommendation runs appear in the generated environment-scoped model list.
After changing model scope, regenerate that list with `python .github/scripts/check-idor-model-coverage.py --regenerate-environment-models`, then run the same command without the regeneration flag.

Backend tests cover run reuse, refresh windows, permissions, consent, source filtering, output validation, and goal preservation.
Frontend tests cover the initial run, manual updates, polling, project isolation, and the setup feature flag.
Draft tests cover event and action mapping, explicit saves, duplicate-click prevention, and retries after failed saves.
They also cover reviewing existing goals and avoiding duplicate saves from stale drafts.
Storybook covers analysis in progress, saved results, updates, failure, empty results, missing consent, and narrow layouts.

The standalone recommendation evaluation uses eleven synthetic business cases and calls the same generator, gateway client, tool schema, and parser as production.
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
