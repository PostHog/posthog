# Hogbox preview — frontend-build CI path validation

Throwaway marker. It exists only to exercise the `hogbox-preview` workflow's
frontend branch: `Detect frontend changes` matches any path under `frontend/`,
so this file forces the FE path in `.github/workflows/hogbox-preview-env.yml`
to run end-to-end:

- `pnpm --filter=@posthog/frontend... install`
- `bin/turbo --filter=@posthog/frontend build` + `pnpm build:products`
- tar `frontend/dist` → hand to the tool via `--frontend-dist`
- in-box: lay the dist in, re-run `collectstatic`, dual-mount `frontend/dist` + `staticfiles`

This PR is based on `feat/devex/hogbox-preview` and gets closed (branch deleted)
once the path is green. Tracking: PostHog/posthog#62672.
