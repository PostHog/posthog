# Marketing analytics review and rollout plan

Status: proposal, 2026-09-10. No remote PRs, deployments or flag changes were made by this review.

## Scope and ownership

Review the two local commits after `779cdc85f83`, tracked working-tree changes and untracked Marketing files. Exclude unrelated changes to sessionRecordingViewedLogic.ts, pageReportsLogic.ts and services/stripe-mock/uv.lock. Split marketingAnalyticsLogic.ts by actual behavior, not its generated formatting changes. The existing Setup, Attribution and Retention implementations are dependencies, not new features to claim in these PRs.

See QAREPORT.md for review findings and validation limits. This plan does not imply merge approval.

## Flag strategy

Reuse `new-marketing-analytics-dashboard` as the temporary UI rollout switch. Keep its off branch functional until the final cleanup PR. Do not create a flag for every card or tab.

Add one separate proposed flag, `marketing-analytics-auto-initialize-goals`, before rolling out automatic writes. Check it server-side before scanning events or writing goals, using the same identity and group targeting as the frontend. A stale client must not bypass the kill switch. Keep normal manual goal CRUD available when this flag is off. Reading already-created notices must not require performing initialization again; use the existing read/config path or an explicitly read-only response.

| UI flag | Automatic goals flag | Expected behavior                                                                                                                  |
| ------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Off     | Off                  | Existing dashboard and onboarding; no automatic writes.                                                                            |
| On      | Off                  | Guided dashboard, Setup, manual goals and source suggestions; no automatic writes.                                                 |
| On      | On                   | Guided dashboard plus eligible admin-triggered initialization once per project.                                                    |
| Off     | On                   | Do not initialize from the UI. Prevent unintended initialization from stale clients by defining the backend dependency explicitly. |

Resolve the existing `marketing-analytics-setup` dependency in one contract PR. The UI currently shows Setup when either Setup or the new dashboard flag is enabled, while setup_plan/apply_setup_ops check only the Setup flag. Prefer a shared effective predicate (Setup OR dashboard) on both sides, with matching targeting and tests. Coordinated flag cohorts alone are a temporary operational workaround, not a substitute for correct fallback behavior.

Decide explicitly whether the umbrella dashboard flag enrolls Retention/Attribution. Until their owners approve inclusion, keep their existing release gates effective within the dashboard. Revenue depends on attribution. Preserve the parent Marketing product gate too.

Use consistent project/organization cohorts where supported for a feature that writes shared project configuration. Current Setup evaluation uses person identity plus organization groups; do not silently switch the backend to team targeting while the frontend still targets people. Test admins and members within the same enrolled project.

Rollback means stopping new writes and returning to the old UI. It must not delete goals, reverse their edits or remove the additive schema field. Existing goals remain manageable in the old configuration UI. Re-enabling the flag must respect the initialization marker and per-item dismissals.

## Merge sequence

Use small independently reviewable PRs, merging each foundation before extending the chain. Prepare a stack only if parallel review is useful; do not keep a deep stack or push incomplete increments repeatedly.

| PR                               | Scope                                                                                                                                                                   | Dependencies and release                                                                                                                                |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Correctness fixes             | Integration-filter sanitizer; project config synchronization; confirmed review blockers with regression coverage. Separate unrelated user edits and typegen-only churn. | Ship safe existing-flow fixes without the new dashboard flag. Review sanitizer behavior against legacy non-integrated traffic controls.                 |
| 2. UI and Setup flag contract    | Effective Setup availability, parent/explorer release gates, old URLs and flag-off fallback, no automatic goal writes.                                                  | Foundation for UI rollout. Verify every supported flag combination before merge.                                                                        |
| 3. Traffic dashboard             | Acquisition, correct session-weighted Engagement, existing comparison renderers, navigation/icons, old ads view moved to Ad performance.                                | Behind dashboard flag. Require query parity and representative cold/warm timings.                                                                       |
| 4. Explorers and empty states    | Reuse Retention/Attribution; Revenue selection; configuration cards and Setup links.                                                                                    | Dashboard flag plus agreed explorer gates. No new attribution algorithm or blended ROAS. Can be combined with PR 3 only if the review stays manageable. |
| 5. Guided notices                | Source logos/examples, accordion persistence, per-item dismiss, View/editor reuse, Setup links.                                                                         | Dashboard/Setup contract. No automatic source connections. Keep generic guidance usable when discovery fails.                                           |
| 6. Initial goals backend         | Nullable migration, idempotent initialization, audit trail, generated API types, server kill switch, normalized-name handling and concurrency tests.                    | Deploy additive migration before endpoint use. Automatic-goals flag off by default. Can merge before PR 5 without activating it.                        |
| 7. Initial goals activation      | Frontend initialization and creation notices using PR 6; safe refresh and tenant switching; consistent edited/deleted goal state.                                       | Both flags; enable for internal cohorts first. Do not infer revenue/new-user semantics from frequency alone.                                            |
| 8. Demo and regression scenarios | Generator tests and reusable local fixtures for empty, traffic-only, returning visitors, prior period, revenue and broken integrations.                                 | Development tooling only. No demo data or local flag configuration deployed to customer projects. Can merge early to support PRs 3-7.                   |

Do not split a regression from its required fix just to meet this numbering. Place companion documentation and tests in the PR that changes the behavior. Before creating real PRs, inspect current master, migration numbering, the repository PR template and existing open branches; the local base used for this review is not proof of current mergeability.

## Validation and rollout gates

1. Test old and new flows with flags off/on, Setup off/on, explorer flags off, admin/member, current-project switch during pending requests, no events, traffic only, pre-existing goals, deleted initial goals and missing warehouse tables.
2. Verify session averages and bounce rate against Web Analytics for uneven pageviews per session. Verify previous-period alignment, missing versus zero, attribution model/window and revenue currency/filter semantics.
3. Test concurrent initialization, manual creation racing initialization, normalized event-name collisions, retry after failure, repeated empty-project visits and disabling the backend flag while a client is open.
4. Run targeted backend/Jest suites, frontend lint/type checks and generated-schema checks. Record unrelated baseline failures separately. Run CI preflight before pushing; do not skip hooks.
5. Start with internal projects, then an opt-in pilot, then staged cohorts (for example 5%, 25%, 100%). Expand only after observed correctness and latency are acceptable relative to the previous flow; percentages are a proposal, not configured rollout rules.
6. Observe dashboard/query error rate, p50/p95 cold and warm latency, requests per visit, Setup scan failures, initialization failures/latency, duplicate goals, manual edits/deletes of automatic goals and successful setup completion. Avoid capturing raw event properties in rollout telemetry.
7. Stop expansion on cross-project state leakage, incorrect metrics, duplicate writes or material query-cost regression. Disable automatic initialization independently; disable the UI flag if navigation or core analysis regresses.

## Agreed scope update — 2026-09-11

- Ad performance keeps the existing ads view. Show "Include conversion goals" only when the project has conversion goals; default it to on.
- Remove mandatory onboarding for the new dashboard cohort. Show available traffic immediately, with configuration actions pointing to Setup. Preserve the legacy flow while the rollout flag is off.
- Proceed with source suggestions (logos, event evidence, explicit connection, individual dismissals, persisted expansion) and automatic initial goals (1–3 eligible goals, idempotent creation, review in Dashboard and Setup).
- Customer and Revenue classification already exists in master for new and existing goals. Reuse it; a distinct New user classification remains separate work.
- Acquisition still needs to display outcomes from Customer goals. Do not count all conversions as newly acquired customers.
- Follow-up: connect ad spend, newly acquired customers and attributed revenue. Start with channel/source/campaign drilldowns, customer acquisition cost and ROAS, using consistent attribution, dates and currencies. Distinguish attributed revenue from revenue generated by the acquired-customer cohort; show missing spend as unavailable rather than zero.
- Instrument each new interaction in its feature PR; update the Marketing usage dashboard separately.

## Future PRs

- **Acquisition: new-customer conversion goals:** show acquisition outcomes from goals explicitly marked as new customer, alongside visitors and sessions. Let users select or configure these goals in Setup. Reuse the supported goal semantics; distinguish new customers from new users and deduplicate people across goals before presenting a combined total. Ship separately from the initial Acquisition metrics PR.

- **Remove legacy onboarding after rollout:** today the preview bypasses both the setup gate and ads onboarding, but the old path still exists for rollback. After full adoption and a stable observation period, remove Onboarding/marketingOnboardingLogic and obsolete gating only after checking every reference and entry point. Keep guided empty states and Setup. Remove temporary flags and stale stored-tab handling only when old URLs still resolve safely.
- **New-user goal semantics:** add a distinct supported flag/schema and query definition for acquisition/retention. Customer is not synonymous with new user. Support marking existing goals or creating one; define first-ever versus first-in-window and identity merge behavior.
- **Automatic revenue suggestions:** detect a credible numeric amount/currency definition, distinguish event/action and warehouse goals, handle refunds and currencies, and make the inferred configuration reviewable. Keep uncertain cases as suggestions. Current initialization creates count goals only.
- **Engagement enrichment:** pages per session and further measures after agreeing on definitions and reusing compatible Web Analytics queries. Fix current correctness before adding more metrics.
- **Precompute:** start with WebOverview live/precomputed parity, then shared WebTrends routing. Keep Sessions when considering WebStats; treat engagement breakdowns and attribution/retention separately. Keep existing compute flags independent of the UI rollout. Measure cold, warm and forced refresh separately.
- **Page visibility:** independent product/query definition and data-source work; do not attach it to this rollout's acceptance criteria.
- **Source evidence:** illustrative UTM examples are currently labeled as such. Real clickable evidence needs an actual sampled event and its permissions, not a fabricated event link.
- **Onboarding copy cleanup:** Setup still contains legacy claims that integrations are required for the dashboard. Update to distinguish website analytics from Ad performance, using existing components.

## Completion criteria

A merged preview is not the same as global launch, and global launch is not legacy cleanup. The first release is complete when metrics are correct, flags roll back safely, empty/traffic-only projects work, explicit source connection remains user-driven, and the agreed cohort has passed the validation gates. Subsequent cleanup removes the old onboarding only after rollback is no longer needed.

## Product telemetry acceptance criteria

Include instrumentation with each feature PR, using existing capture conventions; do not defer all measurement until after rollout. Keep reporting/dashboard updates separate from production code changes.

Existing code provides product intent for dashboard interactions, source configuration and settings updates; marketing query performed/failed events; configuration activity logging; and warehouse connection completed/failed events. These are different signals: intent is not successful persistence, audit logging is not automatically a product-analytics event, and source creation is not completed first sync.

- Track new dashboard section usage with a bounded section value and dashboard version, preserving existing overall usage signals. Avoid emitting product-intent API calls for every minor click.
- Record successful goal creation/update/deletion after persistence, with entry_point, creation_method (automatic/manual/suggestion/API), goal kind, revenue/customer flags and initial-goal batch counts. Do not treat an idempotent initialization retry as another creation. Do not label Customer as New user.
- Carry a bounded entry_point from dashboard notice, empty state, Setup, Settings or onboarding through the connection wizard. Reuse warehouse source connect completed/failed where supported. Correlate attempts across OAuth/new tabs, and distinguish connected from first successful data sync. Verify each native/manual connection path instead of assuming one wizard event covers all paths.
- Track source/goal suggestion shown, reviewed and dismissed with bounded suggestion type and surface. A minimized card is not necessarily an impression of each hidden row.
- Attribute traffic WebOverview/Trends query performance to Marketing explicitly; existing Marketing query-runner events alone do not cover those new query kinds. Keep product ownership, cache/precompute status and load-attempt correlation without double-counting retries or cached renders.
- Add funnels for setup entry to completed configuration to successful analysis, plus adoption/return usage by dashboard version. Use project-level aggregation for shared goals/sources and user-level aggregation for navigation; backend team-identity events must not be joined to user funnels as though their distinct IDs were identical.
- Verify event count and properties alongside each PR's UI checks, including failure, cancel, retry and refresh. Exclude local demo traffic from adoption reporting. Do not send raw event properties, credentials, goal names or campaign labels solely for feature telemetry.

Event names and property contracts should be finalized against existing conventions before implementation. This section is a measurement plan, not a claim that the new instrumentation has shipped.
