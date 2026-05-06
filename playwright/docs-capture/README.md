# docs-capture

Auto-captures screenshots/video of PostHog features for `posthog/website` docs.

## How it works

1. UI elements are tagged with `data-feature="<slug>"`
   (e.g. `data-feature="taxonomic-filter"`).
   The same slug can appear on many elements — the registry decides
   which to capture.
2. `features.ts` declares each slug, the docs page it backs, a `setup`
   step, and one or more named `shots` (UI poses to capture).
3. `capture.spec.ts` is a Playwright test that loops the registry, runs
   `setup`, applies each shot's mutation, and screenshots the tagged
   element.
4. `upload.ts` (stub) handles the S3 upload + PR-against-`posthog/website`
   step.
5. `lint-slugs.ts` fails CI if a registered slug isn't tagged anywhere
   in the frontend.

## Adding a feature

1. Tag the most representative element:

   ```tsx
   <div data-feature="my-feature" ...>
   ```

2. Add an entry to `features.ts`:

   ```ts
   {
       slug: 'my-feature',
       docsPath: '/docs/.../my-feature',
       setup: async (page) => { /* navigate + open the panel */ },
       shots: { default: noop },
   }
   ```

3. Run locally:
   `pnpm --filter=@posthog/playwright exec playwright test docs-capture/capture.spec.ts`.
4. Inspect output in `playwright/docs-capture/output/<slug>/`.

## Conventions

- **Slugs**: kebab-case, one per docs page. A feature spanning multiple
  areas reuses the same slug.
- **Selectors**: shots are scoped to `[data-feature="<slug>"]` first;
  full viewport is the fallback when the element isn't measurable
  (popovers, etc.).
- **Determinism**: the runner pins viewport to 1440x900. Avoid
  timestamps, randomized seed data, or animations in shots — they
  show up as noise in the docs PR diff.
