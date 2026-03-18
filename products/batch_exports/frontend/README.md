# Batch exports frontend

## Tests

The batch exports frontend code currently lives in `frontend/src/scenes/data-pipelines/batch-exports/`. Tests reference that location.

### Kea logic tests

```sh
pnpm --filter=@posthog/frontend jest batchExportConfigurationLogic --no-coverage
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
