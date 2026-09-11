# Node.js CI

The ESLint step in `.github/workflows/ci-nodejs.yml` sets a 4 GiB V8 heap limit.
The full type-aware lint pass exceeds the runner's default heap limit of about 2 GiB.
This uses the same limit as the Node.js test jobs and does not change the runner size.

To run the same lint check locally, use `NODE_OPTIONS=--max_old_space_size=4096 pnpm --filter=@posthog/nodejs lint`.
