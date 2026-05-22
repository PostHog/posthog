# File Classification

Classify the PR file list before planning frontend QA. When in doubt, include a
small browser smoke rather than pretending coverage is complete.

| File pattern                                                            | Frontend target                                 | Notes                                                                                       |
| ----------------------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `frontend/src/**/*.tsx`, `frontend/src/**/*.ts`                         | Browser flow                                    | Use `route-finding.md` for scene files. For kea logic, find the scene importing it.         |
| `products/*/frontend/**/*.tsx`, `products/*/frontend/**/*.ts`           | Browser flow                                    | Read the product `manifest.tsx` and route entries.                                          |
| `products/*/manifest.tsx`                                               | Browser flow                                    | Directly inspect `routes`, `urls`, and tree items.                                          |
| `frontend/**/*.css`, `frontend/**/*.scss`, Tailwind class-only changes  | Visual screenshot                               | Capture route screenshots. Do not call it pixel-perfect regression.                         |
| Backend, query, model, or service files                                 | Comment-only unless a frontend route is obvious | This skill is for frontend QA. If a UI flow clearly exercises the change, smoke that route. |
| `posthog/migrations/**`, `posthog/clickhouse/migrations/**`             | Comment-only by default                         | Warn that local stack may be stale. Do not autonomously edit migrations.                    |
| `pnpm-lock.yaml`, `package.json`, `requirements*.txt`, `pyproject.toml` | Comment-only unless user confirms stack updated | Dependency changes can invalidate the local stack.                                          |
| `.github/**`, Dockerfiles, k8s, infra                                   | Usually comment-only                            | Frontend QA may be meaningless for local app behavior.                                      |
| `docs/**`, `*.md`, pure copy outside app UI                             | No frontend target                              | Post "nothing meaningful to frontend QA" if a PR comment is requested.                      |

## Planning Rules

- Use `test-case-design.md` to turn file categories into behavior-focused cases.
- Mixed frontend/backend PR: focus on routes where the frontend visibly uses the changed behavior.
- Product-scoped frontend PR: read `products/<product>/manifest.tsx` first.
- Shared component PR: find importing scenes with `rg` and choose 1-3 high-signal routes.
- If no URL maps, keep a coverage-gap item in the final report.
- If a file exposes user-facing strings, include a screenshot of the route that renders them.

## Test Plan Shape

Each planned case should be concrete enough for a later agent to execute:

```json
{
  "kind": "browser",
  "changed_behavior": "Dashboard filters should persist after save",
  "risk": "User saves a dashboard and loses the selected filter on reload",
  "setup": "Use a dashboard with at least one insight",
  "route": "/dashboard/:id",
  "action": "Change filter, save, reload dashboard",
  "expected": "Saved filter remains visible and no error toast appears",
  "evidence": "Screenshot after reload plus console/network check"
}
```

Use `coverage_gap` for changed files that could not be mapped. Coverage gaps are
honest output, not failures.
