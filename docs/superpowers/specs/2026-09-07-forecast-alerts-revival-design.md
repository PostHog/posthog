# Forecast Alerts Revival Design

## Context

PostHog alerts currently answer two retrospective questions: whether a metric crossed a known threshold, and whether its latest value is anomalous compared with history. Forecast alerts add a prospective question: whether a Trends metric is heading toward an undesirable outcome.

The existing implementation is split across backend PR #68125 and frontend PR #68126. This revival keeps the useful prospective behavior, removes the anomaly-shaped branch of the design, and brings both PRs onto the current alerts architecture.

## Product contract

Forecast alerts offer exactly two conditions:

1. **Predicted threshold breach** warns when an observed metric is expected to cross a fixed upper or lower threshold within a chosen horizon.
2. **Off track for a target** warns when the point forecast for a chosen date fails to reach an `at least` target or stay below an `at most` target.

The removed **Outside expected range** condition is a seasonality-aware anomaly detector: it evaluates the latest observation rather than a future outcome. It and all supporting direction, deviation-mode, deviation-threshold, interval-width, and score-threshold settings are out of scope. A future implementation can add Prophet as an anomaly detector without coupling it to forecast alerts.

Both retained conditions trigger from the point forecast. The preview may show an uncertainty band, but the band is contextual and must not be described as a guaranteed or statistically calibrated best case. The UI does not expose a forecast-versus-best-case sensitivity setting.

## Supported insight scope

The first release supports Trends time series with no breakdown and an hourly, daily, weekly, or monthly interval. A forecast selects one series or formula. Funnels, SQL insights, non-time-series displays, and breakdown series remain unsupported.

Forecasting uses completed insight buckets only. A forecast alert cannot run more frequently than its insight interval: hourly insights may run hourly or less often, daily insights may run daily or less often, and so on. Real-time and 15-minute calculation intervals are unsupported. This validation prevents normal schedules from repeatedly fitting the same completed input without adding forecast-specific persistence or skip states.

At least 48 hourly observations or 14 daily, weekly, or monthly observations are required. The required history also grows with the requested forecast: the evaluator requires at least four historical observations for every future observation. A 13-week target therefore needs at least 52 weeks of history. Training remains bounded to 1,000 observations and two years of lookback.

## Forecast reach

A target date can be at most 92 calendar days ahead in the project timezone. This is a product guardrail, not a claim that every 92-day forecast is reliable. Annual goals should be represented by quarterly milestones.

Future threshold breach uses the same 92-day absolute ceiling and defaults to seven insight intervals, lowered to the most that fit inside the ceiling when seven would pass it. A monthly insight therefore defaults to three intervals. A separate maximum of 250 returned forecast points bounds response size and rendering work while keeping the four-to-one history rule satisfiable under the 1,000-point training cap. Consequently, an hourly insight can look ahead at most 250 hours; longer-lived goals should use daily or weekly buckets.

The target-date limit is checked both from the project-local current date and from the latest completed non-null observation. A stale insight cannot hide a longer effective extrapolation behind an apparently valid target date; it remains inconclusive until fresh data arrives.

The preview explains that shorter horizons are generally more dependable and recommends matching the insight granularity to the planning horizon.

## Evaluation semantics

### Predicted threshold breach

The alert accepts an absolute lower bound, upper bound, or both. Evaluation first checks the latest completed actual value:

- If it is already outside a configured bound, the alert fires as an actual threshold breach and does not describe the event as predicted.
- Otherwise, Prophet forecasts the selected horizon and the alert fires on the first point forecast outside either bound.
- If neither the actual value nor the forecast breaches, the alert remains in or recovers to the not-firing state through the existing alert state machine.

### Off track for a target

The alert accepts a target value, an `at least` or `at most` direction, and a target date. It evaluates the point forecast at the latest forecast bucket whose timestamp is on or before the target date and fires when that projection misses the target. The preview displays the evaluated bucket date when a weekly or monthly insight does not align exactly with the selected date.

The target applies to the insight value at that bucket, not to a sum accumulated between alert creation and the target date. A cumulative business goal must use an insight whose series is already cumulative.

The alert is an early-warning monitor, not a final target-attainment check. It expires without a notification when the target date arrives in the project timezone. The UI makes that expiry behavior explicit before save. No final actual-value evaluation is performed.

## Preview and copy

The forecast preview shows historical observations, the point forecast, a contextual future uncertainty band, and the configured bounds or target. It calls out the first predicted threshold breach or the projected target value and exact evaluated bucket date. Historical uncertainty bands and model-component decomposition are omitted because neither is needed to explain the two alert conditions.

The existing qualitative `Good fit`, `Noisy fit`, and `Poor fit` badge is removed. Its metrics are computed on the fitted history and do not establish future forecast accuracy. Cross-validation and calibrated reliability indicators are deferred.

Alert messages use the insight's existing value formatter so currencies, percentages, and other units are preserved. Dates and expiry decisions use the project timezone. Copy distinguishes an observed breach from a predicted breach and avoids claims that an uncertainty-band edge is an unavoidable outcome.

The model does not infer a metric's valid numeric domain. In particular, it does not automatically clamp arbitrary formulas to zero or percentages to 100 because valid PostHog formulas can be negative or unbounded. The preview exposes the raw projection so an unsuitable fit is visible before save.

## Backend architecture

The existing `ForecastEngine` boundary and Prophet implementation remain. The condition-specific evaluator consumes extracted Trends data and returns the normal `AlertEvaluationResult`, allowing the established state machine and notification path to remain unchanged.

The API model contains only fields used by the two retained conditions. Condition-specific validation rejects irrelevant combinations and enforces the observation, horizon, point-count, and target-date limits. The read-only simulation endpoint retains team access checks, feature-flag gating, and rate limiting.

Forecast execution has bounded fit and prediction work, stable user-safe failures, and no process-global logging or random-number-generator mutations. Expected configuration failures produce stable API errors and disable an invalid saved alert through the existing path. Insufficient or stale data records an inconclusive check that preserves the current alert state and sends no notification. Execution timeouts and other transient engine failures remain retryable through the existing workflow policy.

Generated OpenAPI, frontend, and MCP contracts are regenerated from the backend serializer and schema sources rather than edited by hand.

## Operational limits and rollout

Scheduled fits remain in the existing alert evaluation activity, protected by the cadence, history, training-point, output-point, and timeout bounds above. Forecast logs include condition, interval, input points, output points, duration, and a stable outcome category without metric values or forecast contents.

Creation, update, and simulation remain behind the organization-scoped forecast-alerts feature flag. Existing saved alerts continue to evaluate if rollout targeting later changes; the product flag is not treated as a silent operational kill switch. Rollout begins with internal organizations and expands only after checking fit duration, evaluation failure rate, and alert-worker queue latency. A rollback explicitly disables affected forecast alerts so their state is visible rather than silently pausing them.

## Frontend architecture

The alert mode remains a peer of Threshold and Anomaly detection behind the existing forecast-alerts feature flag. Selecting Forecast reveals one of the two condition-specific forms:

- Predicted threshold breach: absolute threshold bounds and a horizon.
- Off track for a target: direction, value, and date.

The preview is ported to the chart components used by the current alert editor. It reuses LemonUI controls and generated API types, keeps state and API work in the existing Kea logic, and includes loading, empty, validation, and failure states. No legacy Chart.js dependency is reintroduced.

## Data lifecycle

1. The user selects a supported Trends series and forecast condition.
2. The frontend validates local inputs and requests a read-only simulation.
3. The backend extracts completed buckets, validates reach and history, runs Prophet, and returns history plus forecast points.
4. The frontend renders the preview and saves the alert through the existing alert endpoint.
5. Temporal schedules evaluations through the existing alerts workflow.
6. Cadence validation ensures a normal run has a newly completed bucket. Evaluation runs the condition evaluator and hands its result, including an explicit inconclusive outcome for insufficient or stale data, to the existing state machine.
7. Existing notification destinations receive state changes. Target alerts expire silently at their project-local target date.

## Testing and verification

Backend coverage includes condition-specific validation, actual-versus-predicted threshold semantics, first-crossing selection, target direction, target bucket selection, target-date expiry in the project timezone, cadence compatibility, horizon-to-history requirements, state-preserving inconclusive checks, safe error handling, permission and rate-limit behavior, and generated schema output.

Frontend coverage includes mode switching, removal of band-deviation and sensitivity controls, horizon and date validation, explicit expiry copy, preview states, value formatting, and alert payloads. Storybook covers both retained conditions in light and dark themes.

Before publication, run focused backend and frontend tests, alert workflow tests, formatting and lint checks, full backend mypy, frontend TypeScript checking, OpenAPI/MCP generation checks, migration checks, and `git diff --check`. Report CI as passed, failed, pending, or skipped; historical CI is not evidence for the rebased revisions.

## Delivery structure

PR #68125 remains the foundational backend/schema PR. It is rebased onto current `master`, resolves the moved alerts presentation API, simplifies the schema and evaluator, hardens Prophet execution, and regenerates contracts.

PR #68126 remains stacked on #68125. It is rebased after the backend revision, removes the deferred UI, ports the preview to the current charting layer, and retains focused frontend tests and stories.

The feature stays behind the forecast-alerts flag. Documentation describes the two conditions, supported insight scope, quarterly reach, and expiry semantics before the feature is considered merge-ready.

## Explicitly deferred

- Seasonality-aware anomaly or expected-range alerts
- Forecast-versus-best-case sensitivity controls
- Qualitative forecast-fit badges
- More than one quarter of forecast reach
- Breakdown, funnel, SQL, and non-time-series support
- Engines other than Prophet
- Per-series cross-validation and calibrated reliability scores
- Final target-attainment notifications
- Historical uncertainty bands and forecast-component explanations
- Automatic numeric floors or caps inferred from the metric type
