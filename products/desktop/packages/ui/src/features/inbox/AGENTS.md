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
| Pull requests | `/inbox/pulls` | Reports with `implementation_pr_url` set |
| Reports | `/inbox/reports` | Reports without a PR and not currently running |
| Runs | `/inbox/runs` | Reports that are still in progress or waiting on input |
| Archive | `/inbox/dismissed` | Terminal reports: archived/suppressed (`status === "suppressed"`) and resolved-by-merged-PR (`status === "resolved"`) |

Reports have one canonical detail route: `/reports/$reportId`. The old
`/inbox/{reports,pulls,dismissed}/$reportId` and space-report URLs replace-redirect
there. Runs remain at `/inbox/runs/$reportId`.

`ReportPage` renders the shared report, PR, or archived content based on current
status without changing the URL. In-app links carry the source in a validated
`?from=` search param, so it survives a reload, a new tab and a window restore:
the source rail/sidebar remains selected, and the report header breadcrumb links
to that source. `resolveNavigationSource` in `router/reportNavigation.ts` is the
only place that reads a source path; ask it for the label, space or feed rather
than matching the href again. A report with no source reads as
`Self-driving / <space>` and never renders inside another page's chrome.
The header identifies the object and links to its owning space rather than
treating ownership as a back destination. Report opening must not reset Inbox
filters. Restore updates the canonical page in place. Existing embedded Activity
previews remain supported.

The Archive tab (route `/inbox/dismissed`, user-facing label "Archive") is
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

Each dismissed report shows why it was suppressed (`dismissal_reason`), labelled
via `dismissalReasonLabel` beside a red dot, with `dismissal_note` as a tooltip. These
are denormalised onto the list `SignalReport` by the backend serializer — the
same artefact-lift pattern as `priority`/`actionability`/`already_addressed` —
so cards avoid an N+1 per-card artefact fetch. Unknown reason codes fall back to
the raw value; cards with no dismissal artefact simply omit the label.

Responder configuration is **not** an Inbox tab. It lives in Settings under the `agents` category (`/settings/agents`), on the Connections tab beside the scout fleet (`features/scouts/`). The legacy `/agents` and `/inbox/agents` routes redirect there.

Reviewer scope is a UI preference stored in `inboxReviewerScopeStore`. It filters the list between reports suggested for the current user and reports for someone else. It does not change tab membership; the tab predicates are independent.

The Reports page keeps priority, report status, sort, triage, and reviewer scope above one flat list in the page body. Review and merge plus Needs decision are selected by default; Resolved and Dismissed can be added without switching tabs. PR-backed and resolved rows use a solid neutral border. Reports that need a decision and dismissed rows use a dotted neutral border. Terminal rows recede until hover. Hovered rows keep their solid or dotted treatment while gaining an accent border and stronger background. Report rows show PR repository context and source icons, and omit signal counts. Triage contains only reports that need a decision, not reports waiting for a PR review.

## Ownership Boundaries

Keep the renderer thin:

- Components render reports, route between tabs/details, and call hooks.
- Hooks wrap existing API clients and React Query. They should not orchestrate multi-step business workflows.
- Zustand stores hold UI preferences only: reviewer scope, filters, and selected report IDs used by task creation flows.
- Business decisions, report generation, task orchestration, and source configuration behavior belong in the PostHog Cloud backend or existing main-process services.

Do not add frontend-only controls that imply a backend capability. If the UI exposes a new action, first identify the backend endpoint or task flow that makes it real.

## Routes and Shell

`InboxView` is the layout shell for `/inbox/*`. It owns the page header, tab bar, reviewer scope control, and nested route outlet. Route files live in `apps/code/src/renderer/routes/inbox/`.

Under the spaces layout Self-driving is a rail destination that owns the column
beside the rail (`railPaneHasSidebar`, `railPane.ts`). `InboxPane` draws the
report list there and `ChannelsSidebar` mounts it; the pane beside it holds the
report you picked. So `/inbox` renders `InboxHomePane` (nothing selected, or
triage) instead of the page list, and a row opens the canonical
`/reports/$reportId` with `?from=/inbox`, which is what keeps the rail lit and
the list in place. Off that layout nothing changes: `/inbox` is still the full
`ReportsInboxView` page.

The pane's list is grouped by how long ago each report was found, in the same
widening buckets the task list uses (`groupReportsByAge`, over
`getRelativeDateGroup`): Today, Yesterday, This week, This month, Earlier. A
separator per calendar day left most of the list one row per header, because
reports arrive over weeks. The bucket leads and the chosen sort orders the rows
inside it, so "Priority first" reads as the most urgent thing found today, then
the most urgent thing found this week.

A report opened from a pane closes back to it: `ReportDetailCloseButton` sits at
the end of the header row and navigates to the `?from=` source, leaving the list
standing and the pane on its empty state, the way Activity closes an item. A
report with no source draws no button, because there is no list beside it.

`InboxDetailFrameView` draws one header row, and only its container changes: on
the report's own page it goes to the app header bar through the header store,
and in a pane (Activity) the frame draws its own `ChromeBar` at the top. There
is no second, padded header shape. `DetailBackLink` takes the report as a prop
and renders its crumb trail.

The trail names where the report lives, not the surface it is being read on. So
a report opened from Activity still reads "Self-driving / <report>": the first
crumb is the `?from=` source when a route carried one, and Self-driving
otherwise. Activity is a place you can read a report from, not a place a report
belongs to.

Triage is a route, `/inbox/triage` (`triageRoute.ts`), not a mode flag. It is a
place you can be, so it survives a reload, restores with the rail, and a report
opened out of it carries `?from=/inbox/triage`, which is what makes the close
button land back in the queue. `InboxTriagePane` renders it for both layouts;
the button in the list header is a `Link`, and `useInboxTriageHotkey` gives the
list its "t". Nothing holds triage in a store: the URL is the state.

`useSetHeaderContent` takes the title row or `null`; a view with nothing to name
pushes null. Beside the rail's list the pane names nothing, so `InboxView`
pushes null there and the row collapses. The report a row opens pushes its own.

`useInboxSectionedReports` assembles the list both surfaces read, so the sidebar
and the page can never disagree about what is in the inbox. React Query dedupes
the requests, but paging is a side effect, so only one caller may drive it: the
sidebar pages, `InboxHomePane` passes `autoPage: false`.

The tab components are intentionally simple:

- `PullRequestsTab` partitions scoped reports with `isPullRequestReport`.
- `ReportsTab` partitions with `isReportTabReport`.
- `RunsTab` partitions with `isAgentRunReport`.
- `DismissedTab` (the "Archive" tab) lists its own `useInboxDismissedReports` query (matching `isDismissedReport`); read-only detail route, restore action per card.

The detail components share the same shape: load the report, render a common header, then render tab-specific sections. Detail sections should explain the report in product terms, not expose backend object names.

Filter option tables and their labels live in `filterOptions.tsx`, not in the
component that draws them: the page's separate controls and the pane's menu are
two renderings of one set of choices, and they drifted when each held its own
copy. `hasActiveReportsListFilters` (the filter store) is the single answer to
"is this list filtered", so every surface drawing the list agrees.

## Data Flow

`useInboxAllReports` is the list source of truth. It reads UI scope/filter state, calls the paginated report list hook, returns filtered reports, and computes counts used by the tabs. Multiple tab bodies can call it because React Query dedupes the underlying request.

Tab membership and counts live in `utils/reportMembership.ts`. Keep that file as the canonical place for report partitioning rules so the tab bodies, counts, and tests stay aligned.

Detail screens layer additional data on top of the base report:

- `useInboxReportById(reportId)` for the report record.
- `useInboxReportSignals(reportId)` for contributing findings.
- `useInboxReportArtefacts(reportId)` for structured outputs such as suggested reviewers and repo selection.
- `useReportTasks(reportId, status)` for linked research/implementation tasks.

Ready and pending-input report details offer Resolve and Dismiss beside the other report actions. Resolve records why the work is done; Dismiss records why the report should leave the inbox. Reviewer detail lives in the sidebar, not the title header.

Actionable and pending-input report details also offer Implement. It opens the standard task composer with the report attached, and the repository too when the report selected one, so the user can add direction and choose the model before starting. A report with no repository still opens the composer, where the user picks one. Triage mode keeps the direct Create PR action.

List cards should prefer fields already present in the list response. Fetching per-card secondary data is acceptable only for small, clearly bounded adornments; avoid new N+1 request patterns without a batching plan.

Report rows expose the same primary actions through a right-click menu. Reviewer data stays lazy until its submenu opens. Copy link lets users choose a web or Desktop link; opening a report remains the row's primary interaction.

## Backend Contracts

The Inbox reads from PostHog Cloud's Self-driving backend, currently implemented in the legacy `products/signals/backend` Django app:

- `GET /api/projects/{teamId}/signals/reports/`: paginated report list. Supports filters such as status, ordering, source product, suggested reviewers, and priority.
- `GET /api/projects/{teamId}/signals/reports/{id}/`: single report detail.
- `GET /api/projects/{teamId}/signals/reports/{id}/signals/`: contributing findings.
- `GET /api/projects/{teamId}/signals/reports/{id}/artefacts/`: structured report artefacts.
- `GET /api/projects/{teamId}/signals/reports/{id}/tasks/`: tasks linked to a report.

The shared renderer type for the report is `SignalReport` in `packages/shared/src/domain-types.ts`. If the backend serializer changes, update that type and the client methods in `packages/api-client/src/posthog-client.ts` together.

Report charts: `SignalReport.charts` carries scout-authored chart definitions (`chart_id`, `title`, `query`, `caption?`, `size?`). The desktop app renders them natively in the detail views: `packages/core/src/inbox/reportCharts.ts` classifies the stored query (runnable HogQL/trends vs saved-insight vs link-out fallback), `PostHogAPIClient.runQuery` executes runnable sources against `/api/projects/{teamId}/query/`, and `components/detail/ReportChartCard.tsx` draws the result with `@posthog/quill-charts`. Query kinds the app can't draw degrade to a card that links out to PostHog. Summary prose references charts as `[label](chart:<chart_id>)` links; `SignalReportSummaryMarkdown` turns those into in-page jumps to the chart card (plain text on list rows).

PR refunds: `POST /api/projects/{teamId}/signals/reports/{id}/refund/` refunds a billed PR and archives the report (`PostHogAPIClient.refundSignalReport`). The action is gated behind the `signals-pr-refunds` flag (`SIGNALS_PR_REFUNDS_FLAG`) and `@posthog/core/inbox/refundEligibility`'s `computeRefundEligibility` (shared with the mobile host), which reads `implementation_pr_url`, `refund` (one `SignalReportRefund` per report, ever), `billing_exempt_reason`, and the backend-owned `refund_ineligibility_reason`. The server enforces the same rules, so the gate is display-only; `ReportDetailActions` shows no refund action when the report is ineligible.

Card headlines are derived client-side from `summary` by `utils/reportPresentation.ts`; there is no backend headline field.

## Configuration Surface

Responder setup lives in `features/agents/components/AgentsView.tsx`, the Agents settings page, which mounts `ConfigureAgentsSection` on its Connections tab and the scout fleet on the others. This surface composes existing GitHub, Slack, source-toggle, and MCP configuration pieces. Keep setup copy outcome-focused: the user is asking Self-driving to figure out what matters, not choosing internal artefact types.

Onboarding/setup should be task-backed when it starts work. Do not model it as a static checklist if the intended behavior is to launch an agent task.

An empty Reports view has two distinct causes, and they need different copy: nothing configured yet, versus configured with nothing found. `useSelfDrivingSetupStatus` (`hooks/useSelfDrivingSetupStatus.ts`) reads enabled signal source and scout counts to tell them apart. `ReportsInboxView` only sets `showConfigureAgentsEmptyState` when the inbox is empty with no active filters, so a genuinely quiet but configured project still gets "Nothing to review", not the welcome copy again. The welcome state's CTA links to this same configuration surface; it does not duplicate setup logic.

## UI Architecture

The page body is single-column, route-based, and card/list oriented. Do not reintroduce the old split-pane list/detail layout inside it: under the spaces layout the list moved out to the rail's sidebar column, which is app chrome shared with Spaces and Activity, not a pane the page draws.

Header and toolbar buttons take their size from the `Button` prop, never from
hand-written height, padding or text classes: `size="sm"` for a button with a
label, `size="icon-sm"` for an icon-only one. A row of buttons that each carry
their own `h-7 px-2.5 text-[12px]` drifts apart the moment one of them is
edited, and it sits a size away from every other toolbar in the app.

Shared primitives exist to keep the surfaces consistent:

- `InboxDetailPageHeader` for detail headers.
- `DetailSection` for content sections inside detail screens.
- `SignalsList` and the existing detail `SignalCard` for contributing findings.
- Badge and metadata helpers in `components/utils/` and `InboxMetaRow`.
- `SOURCE_PRODUCT_META` for source-product labels and icons.

When adding or changing UI, reuse those primitives first. Avoid encoding one-off layout systems inside a tab component.

Components come from `@posthog/quill`; layout is `div`s with Tailwind. Radix is banned — see [UI Components](../../../../../AGENTS.md#ui-components) in the root `AGENTS.md`. Inbox files that still import `@radix-ui/themes` are legacy: when you edit one, drop the Radix import rather than extending it (`Flex`/`Box` → `div` + Tailwind, `Text`/`Button`/`Badge`/`Tooltip` → the quill component of the same name).

## Things to Avoid

- Do not add any `@radix-ui/*` import. Use `@posthog/quill` plus `div` + Tailwind.
- Do not reuse the deleted legacy `ReportListRow`, `ReportDetailPane`, or old list/detail stores.
- The Inbox title is a breadcrumb row, not a page header. `InboxView` pushes it into the header store and `ContentHeader` draws it, the same tight row task detail and the loop scenes use. Do not add a second in-page title above the list. Beside the rail's list the pane draws no row at all, because an empty pane and triage name nothing the column's own title does not already say. The row comes back for the report a row opens, which pushes its own crumb and actions.
- Responder configuration stays in Settings (`/settings/agents`). The Inbox header carries a "Configure agents" link toward it, but do not embed configuration UI in the Inbox itself.
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
