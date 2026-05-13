# URL Mapping

The URL walker is a best-effort runtime aid, not a source of truth. Its job is
to give the QA agent likely routes to exercise and to surface coverage gaps.

## Sources

Read these at invocation time:

- `frontend/src/scenes/scenes.ts`
- `frontend/src/scenes/appScenes.ts`
- `products/*/manifest.tsx`

Do not maintain a hardcoded route table inside the skill.

## Core App Routes

`frontend/src/scenes/scenes.ts` defines `routes` with entries like:

```ts
[urls.dashboard(':id')]: [Scene.Dashboard, 'dashboard']
```

`frontend/src/scenes/appScenes.ts` maps `Scene.Dashboard` to an import path like:

```ts
[Scene.Dashboard]: () => import('./dashboard/Dashboard')
```

The walker correlates changed file paths with imported scene modules and returns
the matching route expressions.

## Product Routes

Product manifests usually define:

```ts
routes: {
    '/visual_review': ['VisualReviewIndex', 'visualReviewIndex'],
}
```

and scenes with imports:

```ts
VisualReviewIndex: {
    import: () => import('./frontend/scenes/VisualReviewIndexScene'),
}
```

The walker correlates changed files under `products/<product>/` with scenes and
routes in that product's manifest.

## Dynamic Routes

Routes with placeholders such as `:id`, `:runId`, or `:sourceId` need runtime
data. Keep the placeholder in the test plan and let the execution step pick an
existing object from the UI or create a minimal fixture only when safe.

Do not fabricate IDs in the final report as if they were tested.

## Coverage Gaps

Report a gap when:

- A changed frontend file has no route mapping.
- A route is feature-flagged or redirect-only and cannot be reached locally.
- The route needs data that the local stack does not have.
- The file is a shared component with too many importing scenes to cover in one
  run.

Coverage-gap rows should include the changed file and the reason mapping failed.
