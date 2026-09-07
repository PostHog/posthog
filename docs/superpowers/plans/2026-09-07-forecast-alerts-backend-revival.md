# Forecast Alerts Backend Revival Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR #68125 a current, bounded, and reviewable backend foundation for predicted-threshold and target-by-date alerts.

**Architecture:** Keep forecasting behind the existing `ForecastEngine` boundary, dispatch it from the normal alert evaluator, and carry actual, firing, and inconclusive outcomes through the existing state machine. Define the public contract in the Pydantic schema and DRF serializer, then regenerate every downstream OpenAPI, frontend, and MCP artifact.

**Tech Stack:** Django, Django REST Framework, Pydantic, Temporal, Prophet, pytest, mypy, OpenAPI generation, TypeScript generation.

**Spec:** `docs/superpowers/specs/2026-09-07-forecast-alerts-revival-design.md`

## Global Constraints

- Keep this PR limited to backend behavior, schema sources, generated contracts, the migration, dependency metadata, and user-facing documentation.
- Support only Trends time series with one selected series or formula, no breakdown, and hourly/daily/weekly/monthly intervals.
- Support only predicted threshold breach and off track for a target. Remove expected-range evaluation and all of its configuration fields.
- Enforce a 92-calendar-day reach, 250 output points, 1,000 training points, two-year lookback, and four historical observations per forecast observation.
- Treat insufficient or stale input as inconclusive; do not resolve a firing alert and do not send a notification.
- Never hand-edit generated API or MCP files. Regenerate them from schema and serializer sources.
- Preserve the existing alert delivery and state-transition machinery.
- Use signed conventional commits and plain Git. Do not push until the complete stack passes local preflight.

---

## Task 1: Restack the backend branch on current master

**Files:**

- Rebase scope: all files in `git diff --name-only origin/master...forecast-alerts-backend`
- Preserve: `docs/superpowers/specs/2026-09-07-forecast-alerts-revival-design.md`
- Preserve: this plan

- [ ] Record `origin/master`, `origin/forecast-alerts-backend`, and local `HEAD` SHAs, and create a recoverable local backup ref.
- [ ] Run `git rebase --rebase-merges --gpg-sign origin/master`.
- [ ] Resolve the alerts API move by applying forecast serializer and simulation behavior to `products/alerts/backend/presentation/views/alert.py` and its current tests under `products/alerts/backend/tests/api/test_alert.py`.
- [ ] Resolve `pyproject.toml` and `uv.lock` by preserving current master dependencies plus the single Prophet dependency required by this feature.
- [ ] Remove the obsolete `products/alerts/backend/api/alert.py` and `products/alerts/backend/api/test/test_alert.py` paths after their relevant delta has moved.
- [ ] Confirm the restacked branch contains only the intended backend foundation with `git diff --stat origin/master...HEAD` and `git diff --check`.

## Task 2: Reduce the forecast contract to the two approved conditions

**Files:**

- Modify: `posthog/schema.py`
- Modify: `posthog/schema_enums.py`
- Modify: `products/alerts/backend/models/alert.py`
- Modify: `products/alerts/backend/models/test/test_alert.py`
- Modify: `products/alerts/backend/evaluation/validation.py`
- Modify: `posthog/tasks/alerts/test/test_validate_alert_config.py`

- [ ] Add failing schema and validation tests proving that predicted-threshold accepts bounds plus a horizon, target-by-date accepts direction/value/date, and irrelevant or removed expected-range fields are rejected.
- [ ] Add failing tests for unsupported breakdowns, unsupported intervals, calculation cadence faster than the insight bucket, more than 92 calendar days, more than 250 output points, fewer than four history points per forecast point, and more than 1,000 training points.
- [ ] Run `hogli test posthog/tasks/alerts/test/test_validate_alert_config.py products/alerts/backend/models/test/test_alert.py` and confirm the new assertions fail for the intended reasons.
- [ ] Replace the optional-field configuration object with a discriminated two-condition contract whose branches make required fields explicit.
- [ ] Centralize interval-to-duration and reach calculations so save, simulate, and scheduled evaluation share the same limits.
- [ ] Keep the JSON model field nullable for non-forecast alerts and preserve backwards-safe migration behavior.
- [ ] Run the focused tests again and confirm they pass.
- [ ] Commit with `git commit -S -m "refactor(alerts): narrow forecast alert contract"`.

## Task 3: Make Prophet execution bounded and process-safe

**Files:**

- Modify: `products/alerts/backend/forecasting/engine.py`
- Modify: `products/alerts/backend/forecasting/prophet_engine.py`
- Modify: `products/alerts/backend/forecasting/test/test_prophet_engine.py`
- Modify: `products/alerts/backend/forecasting/__init__.py`

- [ ] Add failing tests for 1,001 training points, a 251-point result, fit timeout, prediction timeout or bounded execution failure, deterministic construction without mutating NumPy's global random state, and no mutation of global `cmdstanpy` logger state.
- [ ] Add a failing test showing the engine returns only history, point forecast, and future uncertainty bounds; it must not return historical bands, model components, or fit-quality labels.
- [ ] Run `hogli test products/alerts/backend/forecasting/test/test_prophet_engine.py` and confirm the new tests fail.
- [ ] Keep Prophet imported lazily and enforce limits at the engine boundary even when callers bypass API validation.
- [ ] Use instance-local model configuration and scoped failure handling; remove process-global logger disabling, global random seeding, and the global fit lock.
- [ ] Convert predictable invalid-input failures to stable forecast configuration errors while preserving timeout and execution failures as retryable engine errors.
- [ ] Log only condition, interval, input/output point counts, duration, and a stable outcome category.
- [ ] Run the focused engine tests and confirm they pass.
- [ ] Commit with `git commit -S -m "fix(alerts): bound forecast execution"`.

## Task 4: Implement the approved forecast evaluation semantics

**Files:**

- Modify: `products/alerts/backend/evaluation/contract.py`
- Modify: `products/alerts/backend/evaluation/dispatcher.py`
- Modify: `products/alerts/backend/evaluation/forecast.py`
- Modify: `products/alerts/backend/evaluation/formatting.py`
- Modify: `products/alerts/backend/evaluation/test/test_forecast.py`
- Modify: `products/alerts/backend/insight_alert_state_machine.py`
- Modify: `products/alerts/backend/test/test_insight_alert_state_machine.py`

- [ ] Add failing tests proving an already-breached latest actual value fires as an observed breach, otherwise the first future point outside a bound fires as predicted, and no crossing returns a non-firing result.
- [ ] Add failing target tests for `at least`, `at most`, latest forecast bucket on or before the target date, exact evaluated bucket reporting, and target meaning the value in that bucket rather than a sum.
- [ ] Add failing tests showing values and thresholds use the insight's `ExtractionResult.value_formatter` in alert copy.
- [ ] Add failing tests showing insufficient and stale input return an explicit inconclusive result, preserve both firing and non-firing state, and enqueue no notification.
- [ ] Run `hogli test products/alerts/backend/evaluation/test/test_forecast.py products/alerts/backend/test/test_insight_alert_state_machine.py` and confirm the new assertions fail.
- [ ] Implement actual-first threshold evaluation, first future crossing selection, and target bucket selection using the last bucket timestamp less than or equal to the configured date.
- [ ] Thread `is_inconclusive` through `AlertEvaluationResult` into the existing state-machine check input without overloading a missing value as a successful clear.
- [ ] Remove expected-range evaluation, fit-quality decisions, model-component output, and historic uncertainty output.
- [ ] Run the focused evaluation and state-machine tests and confirm they pass.
- [ ] Commit with `git commit -S -m "feat(alerts): evaluate bounded forecast conditions"`.

## Task 5: Align saved-alert, simulation, and Temporal lifecycle behavior

**Files:**

- Modify: `products/alerts/backend/presentation/views/alert.py`
- Modify: `products/alerts/backend/tests/api/test_alert.py`
- Modify: `posthog/rate_limit.py`
- Modify: `posthog/temporal/alerts/activities.py`
- Modify: `posthog/temporal/alerts/types.py`
- Modify: `posthog/temporal/alerts/workflows.py`
- Modify: `posthog/temporal/tests/test_alerts_activities.py`
- Modify: `posthog/tasks/alerts/utils.py`
- Modify: `posthog/tasks/alerts/test/test_utils.py`

- [ ] Add failing API tests for organization-scoped feature gating on create, update, and simulation; team and insight-viewer access; throttling; stable validation errors; and retryable engine errors that are not converted to configuration errors.
- [ ] Add failing lifecycle tests showing target alerts expire without a notification when the target date arrives in the project timezone, including a UTC boundary case.
- [ ] Add failing lifecycle tests showing existing forecast alerts continue evaluating if feature-flag targeting later changes, while new creation/update/simulation remain gated.
- [ ] Add a failing Temporal activity test proving an inconclusive forecast records an inconclusive check and preserves state.
- [ ] Run `hogli test products/alerts/backend/tests/api/test_alert.py posthog/temporal/tests/test_alerts_activities.py posthog/tasks/alerts/test/test_utils.py` and confirm the new assertions fail.
- [ ] Implement one shared feature-gate helper for mutating and simulation entry points without putting the scheduled execution path behind the rollout flag.
- [ ] Implement project-timezone target expiry before forecast work and return the existing successful no-notification workflow result.
- [ ] Keep simulation read-only, permission checked, rate limited, and limited to stable user-safe errors.
- [ ] Run the focused API, Temporal, and task tests and confirm they pass.
- [ ] Commit with `git commit -S -m "fix(alerts): harden forecast alert lifecycle"`.

## Task 6: Regenerate public contracts and document the feature

**Files:**

- Modify by generation: `frontend/src/queries/schema.json`
- Modify by generation: `frontend/src/queries/schema/schema-general.ts`
- Modify by generation: `products/alerts/frontend/generated/api.schemas.ts`
- Modify by generation: `products/alerts/frontend/generated/api.ts`
- Modify by generation: `products/alerts/frontend/generated/api.zod.ts`
- Modify: `products/alerts/mcp/tools.yaml`
- Modify by generation: `services/mcp/src/api/generated.ts`
- Modify by generation: `services/mcp/src/generated/alerts/api.ts`
- Modify by generation: `services/mcp/src/tools/generated/alerts.ts`
- Modify by generation: `services/mcp/tests/unit/__snapshots__/tool-schemas/alert-create.json`
- Modify by generation: `services/mcp/tests/unit/__snapshots__/tool-schemas/alert-update.json`
- Modify by generation: `services/mcp/tests/unit/__snapshots__/tool-schemas/alerts-list.json`
- Add or modify: the current published insight-alert documentation located from the docs navigation and existing alert links

- [ ] Update serializer help text and `products/alerts/mcp/tools.yaml` from the approved two-condition contract.
- [ ] Run `hogli build:openapi` and `hogli build:skills`; do not edit their output manually.
- [ ] Review the generated diff for removed expected-range fields, correct discriminated branches, simulation response shape, and no unrelated schema churn.
- [ ] Add user documentation covering supported Trends shapes, two forecast paths, quarterly reach, bucket semantics, silent target expiry, and the forecast-is-an-estimate caveat.
- [ ] Run the generated-schema snapshot tests and documentation checks selected by the build commands.
- [ ] Commit with `git commit -S -m "docs(alerts): document forecast alerts"`.

## Task 7: Verify and self-review the backend PR

- [ ] Run every focused test file changed by this PR with `hogli test`.
- [ ] Run alert Temporal workflow tests, including the repository's sandbox runner if required by `posthog/temporal/README.md`.
- [ ] Run `hogli ci:preflight --fix`.
- [ ] Run `uv run mypy --cache-fine-grained .`.
- [ ] Run migration consistency checks for `products.alerts` and confirm `max_migration.txt` names the new leaf.
- [ ] Run `git diff --check` and inspect `git diff --stat origin/master...HEAD`.
- [ ] Re-read every changed source file and remove duplicate logic, stale fields, dead expected-range code, unsafe error text, and explanatory comments that restate the implementation.
- [ ] Confirm generated files exactly match fresh generation and the worktree is clean.
- [ ] Update PR #68125's body with scope, testing, rollout, migration, and screenshots-not-applicable sections using the repository's current PR template.
- [ ] Push the restacked backend branch with `--force-with-lease` only after every required local gate is green, then report live CI as passed, failed, pending, or skipped.
