# Batch exports frontend

The batch exports frontend code currently lives in `frontend/src/scenes/data-pipelines/batch-exports/`.

## Architecture

### Logics

```text
batchExportDataLogic          Loads and caches a batch export's config from the API.
    │                           Lightweight, mountable independently (e.g. from hog function backfills).
    │
batchExportConfigFormLogic      Form logic for creating/editing batch export configurations.
    ├── connects to             Owns form state, validation, dirty-checking, test steps, save/delete.
    │   batchExportDataLogic  Reads config data from batchExportDataLogic.
    │
batchExportRunsLogic            Loads and manages batch export runs.
    ├── connects to             Grouping by date, retry, cancel, pagination.
    │   batchExportDataLogic
    │
batchExportBackfillsLogic       Loads and manages batch export backfills.
    ├── connects to             Listing, cancellation, polling for row estimates.
    │   batchExportDataLogic
    │   batchExportBackfillModalLogic
    │
batchExportBackfillModalLogic   Form logic for the backfill creation modal.
    ├── connects to             Date range selection, schedule display, submission.
    │   batchExportDataLogic
    │
batchExportSceneLogic           Tab navigation and URL sync for the batch export scene.
                                Defined inline in BatchExportScene.tsx.
```

### Components

| Component                         | Description                                                                         |
| --------------------------------- | ----------------------------------------------------------------------------------- |
| `BatchExportScene`                | Top-level scene. Mounts `batchExportConfigFormLogic` via `BindLogic`, renders tabs. |
| `BatchExportConfiguration`        | Configuration/editing form (uses `batchExportConfigFormLogic`).                     |
| `BatchExportConfigurationButtons` | Save and clear-changes buttons for the config form.                                 |
| `BatchExportEditForm`             | The form fields for editing a batch export destination.                             |
| `BatchExportRuns`                 | Runs tab — table of export runs grouped by date.                                    |
| `BatchExportBackfills`            | Backfills tab — table of backfills with cancel/create actions.                      |
| `BatchExportBackfillModal`        | Modal for creating a new backfill with date range picker.                           |
| `BatchExportsMetrics`             | Metrics tab — charts for export performance.                                        |
| `BatchExportIcon`                 | Renders the icon for a batch export destination type.                               |

### External consumers

`HogFunctionBackfills` (in `scenes/hog-functions/backfills/`) renders the backfills tab
for hog function destinations backed by a batch export. It mounts `batchExportDataLogic`
and `batchExportBackfillsLogic` via `BindLogic` — this works because these logics only
depend on the lightweight config logic, not the heavyweight form logic.

## Tests

### Kea logic tests

```sh
pnpm --filter=@posthog/frontend jest batchExportConfigFormLogic --no-coverage
```

Covers: default configuration per service, required field validation, S3 bucket name validation, create/update flows, and API loading.

If tests fail with `Cannot find module 'react'` from `kea-router`, run `pnpm install --force` to fix broken pnpm symlinks.

### Storybook stories

```sh
pnpm storybook
```

Then navigate to **Scenes-App / BatchExports** in the sidebar. Stories: `NewS3Export`, `NewPostgresExport`, `ExistingBigQueryExport`.

### Playwright E2E tests

```sh
pnpm --filter=playwright test e2e/batch-exports.spec.ts
```

Covers creating a new S3 export and validating required fields.

Requires a running backend (`./bin/start`).

You will also need to install Playwright using `pnpm exec playwright install`.
