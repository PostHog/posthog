# Forecast Alerts Frontend Revival Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make PR #68126 a small, current frontend for configuring and previewing the two approved forecast alert paths.

**Architecture:** Treat Forecast as a peer alert mode in the existing editor. Keep form and simulation state in the alert Kea logic, consume only backend-generated types, use condition-specific controls, and render history plus future forecast with the chart layer already used by the current alert preview.

**Tech Stack:** React, TypeScript, Kea, LemonUI, `@posthog/quill-charts`, Jest, Storybook.

**Spec:** `docs/superpowers/specs/2026-09-07-forecast-alerts-revival-design.md`

## Global Constraints

- Stack this PR on the final local backend revision and keep backend/schema generation out of the frontend delta.
- Show only predicted threshold breach and off track for a target.
- Do not expose expected-range, sensitivity, interval-width, deviation, fit-quality, model-component, or historical-band UI.
- Use current LemonUI and `@posthog/quill-charts`; do not reintroduce legacy Chart.js.
- Use generated API types and keep network/form business logic in Kea.
- Show the 92-day limit and silent target expiry before save.
- Use signed conventional commits and plain Git. Do not push until both PRs pass local preflight.

---

## Task 1: Restack the frontend on the finished backend revision

**Files:**

- Rebase scope: all files in `git diff --name-only <old-backend-head>...forecast-alerts-frontend`

- [ ] Record the old backend base, frontend remote head, and local head, and create a recoverable local backup ref.
- [ ] Rebase the frontend-only commits onto the final local backend head while preserving signed commits.
- [ ] Resolve the current alert-editor changes in `AlertDefinitionSection.tsx`, `AlertPreviewCard.tsx`, `alertFormLogic.ts`, and the edit-modal files by starting from current backend/master architecture and replaying only forecast behavior.
- [ ] Drop generated schema/API/MCP files from the frontend delta because they belong to PR #68125.
- [ ] Confirm `git diff --name-status <backend-head>...HEAD` contains only frontend source, tests, and stories.

## Task 2: Model Forecast as a clean third alert mode

**Files:**

- Modify: `products/alerts/frontend/types.ts`
- Modify: `products/alerts/frontend/components/alertModeOptions.ts`
- Modify: `products/alerts/frontend/components/alertModeOptions.test.ts`
- Modify: `products/alerts/frontend/logic/alertFormSchema.ts`
- Modify: `products/alerts/frontend/logic/alertFormSchema.test.ts`
- Modify: `products/alerts/frontend/logic/alertFormLogic.ts`
- Modify: `products/alerts/frontend/logic/alertFormLogic.test.ts`
- Modify: `products/alerts/frontend/utils.ts`
- Modify: `products/alerts/frontend/utils.test.ts`

- [ ] Add failing tests showing Forecast appears only for feature-flagged, supported Trends time series and remains absent for breakdown, funnel, SQL, non-time-series, real-time, and 15-minute insights.
- [ ] Add failing form-schema tests for the exact two discriminated condition payloads, rejecting removed fields and condition-incompatible values.
- [ ] Add failing logic tests for switching among Threshold, Anomaly detection, and Forecast without leaking detector, threshold, or forecast configuration between modes.
- [ ] Add failing save-payload tests proving the frontend submits only generated-contract fields and preserves a loaded saved forecast alert.
- [ ] Run `hogli test products/alerts/frontend/components/alertModeOptions.test.ts products/alerts/frontend/logic/alertFormSchema.test.ts products/alerts/frontend/logic/alertFormLogic.test.ts products/alerts/frontend/utils.test.ts` and confirm the new assertions fail.
- [ ] Implement a single alert-mode derivation and transition path backed by generated forecast types.
- [ ] Remove duplicated schema types from hand-authored frontend files and remove obsolete init registration if the current Kea architecture does not require it.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit with `git commit -S -m "feat(alerts): add forecast alert mode"`.

## Task 3: Build only the approved condition controls

**Files:**

- Modify: `products/alerts/frontend/components/AlertDefinition.tsx`
- Modify: `products/alerts/frontend/components/AlertDefinitionFields.tsx`
- Modify: `products/alerts/frontend/components/AlertDefinitionSection.tsx`
- Modify: `products/alerts/frontend/views/ForecastSelector.tsx`
- Modify: `products/alerts/frontend/views/ForecastSelector.test.ts`
- Modify: `products/alerts/frontend/logic/forecastReach.ts`
- Modify: `products/alerts/frontend/logic/forecastReach.test.ts`
- Modify: `products/alerts/frontend/components/alertSummary.ts`

- [ ] Add failing component tests showing exactly two choices: predicted threshold breach and off track for a target.
- [ ] Add failing tests for lower-only, upper-only, and two-sided bounds; target `at least` and `at most`; 92 project-local calendar days; cadence no faster than insight interval; four-to-one history messaging; and 250-point hourly reach.
- [ ] Add failing tests confirming expected-range, sensitivity, interval width, deviation settings, fit-quality copy, and final-date notification claims never render.
- [ ] Add failing target tests confirming copy says the insight value in the evaluated bucket and says the alert expires silently on the target date.
- [ ] Run the selector and reach tests and confirm the new assertions fail.
- [ ] Implement separate, compact condition forms with LemonUI components and stable field-level validation.
- [ ] Share interval/reach calculations between eligibility, local validation, and explanatory copy without duplicating backend-only policy.
- [ ] Update alert summaries to distinguish observed breach, predicted breach, and off-track projection without promising certainty.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit with `git commit -S -m "feat(alerts): configure forecast conditions"`.

## Task 4: Port forecast simulation and preview to the current chart layer

**Files:**

- Modify: `products/alerts/frontend/logic/alertLogic.ts`
- Modify: `products/alerts/frontend/components/ForecastSimulationSection.tsx`
- Modify: `products/alerts/frontend/components/AlertPreviewCard.tsx`
- Modify: `products/alerts/frontend/views/ForecastPreview.tsx`
- Modify: `products/alerts/frontend/views/forecastPreviewUtils.ts`
- Modify: `products/alerts/frontend/views/forecastPreviewUtils.test.ts`
- Add or modify: colocated Storybook stories for forecast preview states

- [ ] Add failing Kea tests for debounced or explicit simulation, stale-response rejection after form changes, unsupported/invalid no-request behavior, loading, empty, inconclusive, validation-error, and transient-failure states.
- [ ] Add failing preview utility tests for merging history and future labels, future-only uncertainty bands, first threshold crossing, target projection, and exact evaluated bucket date.
- [ ] Add rendering tests showing the insight value formatter is used and raw negative or over-100 projections are not clamped.
- [ ] Run the focused logic and preview tests and confirm the new assertions fail.
- [ ] Keep simulation effects and stale-request protection in Kea; keep chart-data mapping in pure utilities.
- [ ] Render historical observations, point forecast, future uncertainty band, and threshold/target reference lines using `@posthog/quill-charts` and the existing alert-preview theme/error handler.
- [ ] Remove legacy Chart.js imports, historical uncertainty bands, model-component rendering, and fit-quality badges.
- [ ] Add Storybook stories for both conditions plus loading, validation, empty/inconclusive, and failure states in light and dark themes.
- [ ] Run the focused logic, utility, component, and story checks and confirm they pass.
- [ ] Commit with `git commit -S -m "feat(alerts): preview forecast alerts"`.

## Task 5: Integrate forecast mode into both alert editor layouts

**Files:**

- Modify: `products/alerts/frontend/views/EditAlertModal.tsx`
- Modify: `products/alerts/frontend/views/EditAlertModal/buildWizardSteps.tsx`
- Modify: `products/alerts/frontend/views/EditAlertModal/buildWizardSteps.test.tsx`
- Modify: `products/alerts/frontend/views/InsightAlerts.tsx`
- Modify: `products/alerts/frontend/views/SimulationSummary.tsx`
- Modify: `products/alerts/frontend/components/AlertDefinitionSection.tsx`

- [ ] Add failing integration tests proving both the legacy and redesigned alert editors can create, edit, preview, and save each forecast condition.
- [ ] Add failing tests proving unsupported insights explain why Forecast is unavailable without changing an existing loaded configuration.
- [ ] Add failing tests for keyboard labels, field associations, error placement, and responsive wrapping of the condition controls.
- [ ] Run the affected editor and wizard tests and confirm the new assertions fail.
- [ ] Wire the shared forecast mode and selector into both layouts without duplicating form state or simulation calls.
- [ ] Ensure loading or failed preview never blocks correcting or saving an otherwise valid form unless the backend contract requires simulation success.
- [ ] Run the integration tests and confirm they pass.
- [ ] Commit with `git commit -S -m "feat(alerts): integrate forecast editor"`.

## Task 6: Verify and visually review the frontend PR

- [ ] Run every focused Jest file changed by this PR with `hogli test`.
- [ ] Run `pnpm --filter=@posthog/frontend fix`.
- [ ] Run the full frontend TypeScript check once after all edits.
- [ ] Run the relevant Storybook build or story test command.
- [ ] Render both conditions and every required state in light and dark themes, inspect the output at desktop and narrow widths, and save a QA report if the repository workflow requires one.
- [ ] Run `git diff --check` and inspect `git diff --stat <backend-head>...HEAD`.
- [ ] Re-read every changed file and remove stale expected-range paths, copied backend types, legacy chart imports, dead feature-flag wiring, and unrelated generated changes.
- [ ] Confirm the worktree is clean and the frontend delta remains stacked only on the final backend revision.
- [ ] Update PR #68126's body with scope, testing, visual evidence, and dependency on #68125 using the repository's current PR template.
- [ ] Push the restacked frontend branch with `--force-with-lease` only after both branches pass their required local gates, then report live CI as passed, failed, pending, or skipped.
