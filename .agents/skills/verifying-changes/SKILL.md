---
name: verifying-changes
description: >
  Picks the cheapest check that is enough to confirm a change works, and says when to climb to a more
  expensive one. Use before you report a task done, before you start Storybook, the dev stack or a
  Playwright run to check your own work, and when you are unsure how much verification a diff needs.
  Maps each kind of change (pure logic, DRF serializer or viewset, migration, kea logic, React component,
  CSS, CI workflow, SQL or HogQL, docs or skills) to its sufficient rung and the rung that is wasted.
  `hogli verify --changed` walks the cheap rungs for the current diff and names the next one to run by hand.
  Trigger terms: verify, how do I test this, is this enough testing, start the stack, render it, run e2e.
---

# Verifying changes

Verification is a ladder. Each rung costs roughly ten times the one below it.
Start at the bottom, and climb only when the rung you are on cannot see the thing the diff changes.

| Rung | Check                        | Command                                                                                                 |
| ---- | ---------------------------- | ------------------------------------------------------------------------------------------------------- |
| 1    | Lint, format, typecheck      | `hogli verify --changed` (runs it), or `ruff check`, `pnpm --filter=@posthog/frontend typescript:check` |
| 2    | The nearest unit test        | `hogli test <file>`, `hogli test --changed`                                                             |
| 3    | Serializer and OpenAPI regen | `hogli build:openapi` (needs `hogli up -d`), then commit the generated diff                             |
| 4    | Storybook render             | `pnpm storybook`, open the affected story, compare before and after                                     |
| 5    | The running stack            | `hogli up -d`, `hogli wait`, then exercise the flow                                                     |
| 6    | Playwright or a recorded run | `hogli test playwright/<spec>.spec.ts` against a running stack                                          |

`hogli verify --changed` classifies the diff against master, runs rungs 1 and 2, and stops with the next rung you must run by hand.
It does not call the diff verified while a check is skipped, a check only advises (mypy runs repo-wide, so it lists the command), or no test covers the changed files.
Use `--plan` to see the classification without running anything.

## Decision table

| Change                     | Sufficient rung                                    | Wasted rung                              |
| -------------------------- | -------------------------------------------------- | ---------------------------------------- |
| Pure logic (Python or TS)  | 2: nearest unit test                               | 5: stack                                 |
| DRF serializer or viewset  | 3: OpenAPI regen, plus the endpoint test at rung 2 | 6: Playwright                            |
| Migration                  | 2: migration test, plus `hogli migrations:check`   | 4: Storybook                             |
| Kea logic                  | 2: logic test, plus typecheck                      | 4: Storybook                             |
| React component            | 4: Storybook render                                | 5: stack, unless the data wiring changed |
| CSS only                   | 4: Storybook render                                | 2: unit tests                            |
| CI workflow                | 1: `hogli lint:workflows`, `hogli ci:plan`         | 2: unit tests                            |
| SQL or HogQL               | 2: the ClickHouse-backed query test                | 5: stack                                 |
| Docs or skills             | 1: format, `hogli lint:skills`                     | 2 and above                              |
| Settings, URLs, middleware | 5: running stack                                   | 6: Playwright                            |

A diff that mixes kinds needs the highest sufficient rung among them, and only for the files of that kind.

## Rules that do not change

- **Visual changes still need a render.** The root `AGENTS.md` rule stands: reading the code does not confirm visual or UX work. For a component or CSS change, rung 4 is the floor, not an option.
- **Rung 2 is about where the test lives, not whether to add one.** Use `/writing-tests` before you add or change a test. When a regression is hard to reach cheaply, extract the logic and test it at a lower rung instead of climbing.
- **Rung 1 is not the pre-push gate.** `hogli ci:preflight` stays the push check, see `/running-ci-preflight`. `hogli verify` reuses its lint and format checks, so a pass here usually means a pass there too.

## When the stack is required

Start the stack only when the behavior lives between processes, and no test at rung 2 runs both sides:

- Settings, URL routing, middleware, or the Content Security Policy, because the browser is the only thing that applies them.
- A change that a person has to see in the app: a new scene, a navigation change, or data flowing from ingestion to a UI.
- A Celery task, Temporal workflow, or plugin-server path whose wiring (not its logic) changed.
- A Playwright spec you changed, because it runs against the stack.

The stack is optional for everything else.
Django and ClickHouse-backed tests need the Postgres and ClickHouse services, not the web app, so `hogli up -d` and a scoped `hogli test` is still rung 2.

## Report what you ran

Say which rung you stopped at and why the rung above it was not needed.
If a rung was required and you could not run it, say so and name the command, so a reviewer knows what is unverified.
