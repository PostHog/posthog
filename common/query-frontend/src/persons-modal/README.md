# Persons modal

`PersonsModal` is the drill-down modal that shows the actors (persons, groups, or sessions) behind a data point.
Clicking a point on a trends graph, a funnel step, a retention cell, or a path node opens it with the list of matching actors, where you can search, page through results, save the list as a cohort, export CSV, watch matching session recordings, or inspect an actor's properties timeline.

## How it is driven

The modal is fed by an actors query, usually an `InsightActorsQuery` (or one of its siblings: `FunnelsActorsQuery`, `FunnelCorrelationActorsQuery`, `ExperimentActorsQuery` — see `../schema/schema-general.ts`).
An `InsightActorsQuery` wraps the insight source query and pins the clicked coordinates — `day`, `series`, `breakdown`, `status`, `interval`, `compare`:

```ts
{
    kind: NodeKind.InsightActorsQuery,
    source: { kind: NodeKind.TrendsQuery, series: [...] },
    day: '2026-06-01',
    series: 0,
}
```

Internally the logic wraps this source in an `ActorsQuery` to select, search, order, and paginate the actor rows.

The viz components open it imperatively via `openPersonsModal()` (exported from `PersonsModal.tsx`), which mounts the modal into `document.body`:

```ts
import { openPersonsModal } from '@posthog/query-frontend/persons-modal/PersonsModal'

openPersonsModal({ title: 'Pageview users on Jun 1', query: insightActorsQuery })
```

A legacy `url` prop (pointing at an old persons API endpoint) is still supported as an alternative to `query`.
Callers are e.g. `../nodes/TrendsQuery/viz/datasetToActorsQuery.ts`, `../nodes/FunnelsQuery/funnelPersonsModalLogic.ts`, `../nodes/RetentionQuery/retentionModalLogic.ts` (which uses its own modal), and `../nodes/PathsQuery/pathsDataLogic.ts`.

## Key files

- `PersonsModal.tsx` — the modal component plus `openPersonsModal()` / `OpenPersonsModalProps`. Renders the actor list, search input, query option dropdowns, recordings tab, and export/save-as-cohort actions.
- `personsModalLogic.ts` — kea logic keyed by the query/url props. Owns the current `actorsQuery`, loaded `actors` with pagination (`loadNextActors`, `missingActorsCount`), `searchTerm`, `insightActorsQueryOptions` (the alternative days/series/breakdowns the user can switch between), save-as-cohort flow, exploration URLs, and session recording filters derived from the clicked breakdown.
- `persons-modal-utils.tsx` — title builders (`funnelTitle`, `pathsTitle`) and `cleanedInsightActorsQueryOptions`.
- `SaveCohortModal.tsx` — name prompt when saving the actor list as a static cohort.
- `SessionActorDisplay.tsx` — row rendering for session-type actors.

The kea logic here is an internal implementation detail of the `<Query />` tag and of `openPersonsModal()`.
Consumers should call `openPersonsModal()` (or render `<PersonsModal />` with props) rather than binding `personsModalLogic` directly.
