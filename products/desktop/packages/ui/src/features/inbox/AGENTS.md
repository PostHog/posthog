# PostHog Self-driving Inbox

The Inbox is the PostHog surface for **Self-driving**: agents that watch product signals, summarize what matters, and can ship pull requests. This document is an architecture map for agents working in this area. It explains where responsibilities live, which backend contracts are relied on, and what not to accidentally rebuild.

## Product Model

The renderer still talks to backend endpoints and TypeScript types with the legacy `signals` naming. User-facing copy should say **Self-driving**, **Responder**, **report**, **run**, or **finding** depending on context. Do not rename backend paths or shared API fields unless the PostHog Cloud backend has changed too.

The main objects are:

- `SignalReport`: the unit shown in all Inbox tabs.
- Findings: the source observations that contributed to a report, fetched separately for detail screens.
- Artefacts: structured agent output attached to a report, such as priority, actionability, suggested reviewers, repo selection, and findings from research.
- Report tasks: links from a report to tasks created for research or implementation.

## Information Architecture

Inbox has four tabs and one reviewer-scope control:

| Tab | Route | Membership |
| --- | --- | --- |
| Pull requests | `/code/inbox/pulls` | Reports with `implementation_pr_url` set |
| Reports | `/code/inbox/reports` | Reports without a PR and not currently running |
| Runs | `/code/inbox/runs` | Reports that are still in progress or waiting on input |
| Archive | `/code/inbox/dismissed` | Terminal reports: archived/suppressed (`status === "suppressed"`) and resolved-by-merged-PR (`status === "resolved"`) |

Detail pages live under the same tab: `/code/inbox/<tab>/$reportId`.

The Archive tab (route `/code/inbox/dismissed`, user-facing label "Archive") is
the exception: it holds the two terminal, not-in-inbox states — `suppressed`
(user-archived) and `resolved` (implementation PR merged) — both excluded from
the main pipeline query, so the tab fetches them with a dedicated
`status=suppressed,resolved` query (`useInboxDismissedReports`). Its detail view
(`DismissedReportDetail`) is read-only — summary + evidence, no triage
affordances — and depends on the backend serving these reports on the
`retrieve`/`signals` read paths (PostHog/posthog#64019). Suppressed cards offer a
single Restore action; resolved cards are reference-only (terminal, no restore),
badged "Resolved". Restore uses `useInboxRestoreReport`, which
reuses the `state` action's `potential` ("reopen") transition — the only reopen
path the backend exposes. The reviewer scope control is hidden on this tab since
the archive list is not scoped, and the tab carries no count badge. The
Archive detail is **not** a tracked `InboxDetailTab` (no OPENED/CLOSED
engagement events), since its rank would be measured against the wrong list.

The internal route segment, query key, and component/hook names keep the
`dismissed`/`suppressed` vocabulary (the backend status is `suppressed`); only
the user-facing copy uses "Archive"/"archived".

Each `DismissedReportCard` shows why the report was suppressed (`dismissal_reason`,
labelled via `dismissalReasonLabel`, with `dismissal_note` as a tooltip). These
are denormalised onto the list `SignalReport` by the backend serializer — the
same artefact-lift pattern as `priority`/`actionability`/`already_addressed` —
so cards avoid an N+1 per-card artefact fetch. Unknown reason codes fall back to
the raw value; cards with no dismissal artefact simply omit the chip.

Responder configuration is **not** an Inbox tab. It is the top-level Responders sidebar item at `/code/agents`. The legacy `/code/inbox/agents` route redirects there.

Reviewer scope is a UI preference stored in `inboxReviewerScopeStore`. It filters the list between reports suggested for the current user and reports for someone else. It does not change tab membership; the tab predicates are independent.

## Ownership Boundaries

Keep the renderer thin:

- Components render reports, route between tabs/details, and call hooks.
- Hooks wrap existing API clients and React Query. They should not orchestrate multi-step business workflows.
- Zustand stores hold UI preferences only: reviewer scope, filters, and selected report IDs used by task creation flows.
- Business decisions, report generation, task orchestration, and source configuration behavior belong in the PostHog Cloud backend or existing main-process services.

Do not add frontend-only controls that imply a backend capability. If the UI exposes a new action, first identify the backend endpoint or task flow that makes it real.

## Routes and Shell

`InboxView` is the layout shell for `/code/inbox/*`. It owns the page header, tab bar, reviewer scope control, and nested route outlet. Route files live in `apps/code/src/renderer/routes/code/inbox/`.

The tab components are intentionally simple:

- `PullRequestsTab` partitions scoped reports with `isPullRequestReport`.
- `ReportsTab` partitions with `isReportTabReport`.
- `RunsTab` partitions with `isAgentRunReport`.
- `DismissedTab` (the "Archive" tab) lists its own `useInboxDismissedReports` query (matching `isDismissedReport`); read-only detail route, restore action per card.

The detail components share the same shape: load the report, render a common header, then render tab-specific sections. Detail sections should explain the report in product terms, not expose backend object names.

## Data Flow

`useInboxAllReports` is the list source of truth. It reads UI scope/filter state, calls the paginated report list hook, returns filtered reports, and computes counts used by the tabs. Multiple tab bodies can call it because React Query dedupes the underlying request.

Tab membership and counts live in `utils/reportMembership.ts`. Keep that file as the canonical place for report partitioning rules so the tab bodies, counts, and tests stay aligned.

Detail screens layer additional data on top of the base report:

- `useInboxReportById(reportId)` for the report record.
- `useInboxReportSignals(reportId)` for contributing findings.
- `useInboxReportArtefacts(reportId)` for structured outputs such as suggested reviewers and repo selection.
- `useReportTasks(reportId, status)` for linked research/implementation tasks.

List cards should prefer fields already present in the list response. Fetching per-card secondary data is acceptable only for small, clearly bounded adornments; avoid new N+1 request patterns without a batching plan.

## Backend Contracts

The Inbox reads from PostHog Cloud's Self-driving backend, currently implemented in the legacy `products/signals/backend` Django app:

- `GET /api/projects/{teamId}/signals/reports/`: paginated report list. Supports filters such as status, ordering, source product, suggested reviewers, and priority.
- `GET /api/projects/{teamId}/signals/reports/{id}/`: single report detail.
- `GET /api/projects/{teamId}/signals/reports/{id}/signals/`: contributing findings.
- `GET /api/projects/{teamId}/signals/reports/{id}/artefacts/`: structured report artefacts.
- `GET /api/projects/{teamId}/signals/reports/{id}/tasks/`: tasks linked to a report.

The shared renderer type for the report is `SignalReport` in `apps/code/src/shared/types.ts`. If the backend serializer changes, update that type and the normalizers in `posthogClient.ts` together.

Card headlines are derived client-side from `summary` by `utils/reportPresentation.ts`; there is no backend headline field.

## Configuration Surface

Responder setup lives in `features/agents/components/AgentsView.tsx`, which mounts `ConfigureAgentsSection`. This surface composes existing GitHub, Slack, source-toggle, and MCP configuration pieces. Keep setup copy outcome-focused: the user is asking Self-driving to figure out what matters, not choosing internal artefact types.

Onboarding/setup should be task-backed when it starts work. Do not model it as a static checklist if the intended behavior is to launch an agent task.

## UI Architecture

The current UI is single-column, route-based, and card/list oriented. Do not reintroduce the old split-pane list/detail layout.

Shared primitives exist to keep the surfaces consistent:

- `InboxDetailPageHeader` for detail headers.
- `DetailSection` for content sections inside detail screens.
- `SignalsList` and the existing detail `SignalCard` for contributing findings.
- Badge and metadata helpers in `components/utils/` and `InboxMetaRow`.
- `SOURCE_PRODUCT_META` for source-product labels and icons.

When adding or changing UI, reuse those primitives first. Avoid encoding one-off layout systems inside a tab component.

## Things to Avoid

- Do not reuse the deleted legacy `ReportListRow`, `ReportDetailPane`, or old list/detail stores.
- Do not put page-level Inbox title or navigation into the global app header; `InboxView` owns the Inbox page chrome.
- Do not add a configure shortcut back into the Inbox header; Responders configuration is a sidebar destination.
- Scout (`signals_scout`) is a real Cloud source product. Keep it covered wherever source products surface: `INBOX_SOURCE_OPTIONS`, `SOURCE_PRODUCT_META`, and the scout-name display in `SignalCard`.
- Scout management UI (fleet configuration, run history) lives in `features/scouts/` and is backed by the PostHog Cloud scout endpoints (`/api/projects/{teamId}/signals/scout/`). Do not add scout controls that have no backing endpoint there.
- Do not put preview shims or mock report data in `apps/code/index.html`; the app shell should stay minimal.
- Do not call `electronTRPC` directly from Inbox code. Use the existing API client, React Query hooks, or tRPC client wrappers.
- Do not preserve compatibility with unshipped intermediate UI shapes on this branch. Replace them cleanly.

## Testing

Keep tests close to the pure logic:

- `utils/reportMembership.test.ts` covers tab predicates, reviewer scope, routes, and counts.
- `utils/reportPresentation.test.ts` covers card headline derivation and related text shaping.
- Parser/display helpers such as conventional-commit title parsing and reviewer display should stay unit-tested.

Use typecheck for route and hook integration. Browser screenshots are useful for design review, but preview fixtures/tooling should live outside the production `index.html` shell.
