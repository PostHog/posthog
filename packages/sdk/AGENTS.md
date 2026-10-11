# Using @posthog/sdk

Run `posthog-sdk --agent-help` before a PostHog task; it lists available tool domains, absolute local paths to `api.ts` and both TSV indexes, and workflow guidance.
Use grep or rg on `api-index.tsv` to find methods, then read their JSDoc and named input/output interfaces in `src/generated/api.ts`. `domains.tsv` lists domain counts and import paths.
Read [README.md](README.md) when configuring authentication, project selection, or a Tasks proxy.
Import `{ client }` from `@posthog/sdk` for environment defaults, or `createPostHogClient` for explicit configuration. `@posthog/sdk/discovery` exports static `operations` and `domains` arrays for programmatic exploration.
Inspect required scopes and result types before calling a method. Reuse parameterized scripts in your own skill or scratchpad when a job repeats.
