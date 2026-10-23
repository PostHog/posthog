---
name: verifying-changes
description: >
  Picks the cheapest check that is enough to confirm a change works, and says when a slower one is needed.
  Use before you report a task done, before you start Storybook, the dev stack or a
  Playwright run to check your own work, and when you are unsure how much verification a diff needs.
  Maps each kind of change, such as pure logic, DRF serializer or viewset, migration, kea logic, React component,
  CSS, Django template, CI workflow, SQL or HogQL, or docs and skills, to the layer that is enough and the layer that is wasted.
  `hogli verify --changed` runs the cheap layers for the current diff and names the slower ones left to run yourself.
  Trigger terms: verify, how do I test this, is this enough testing, start the stack, render it, run e2e.
---

# Verifying changes

Verification has six layers, and each one costs roughly ten times the one before it.
Start with the cheapest, and move up only when the current layer cannot see what the diff changes.

| Layer | Check                        | Command                                                                                          |
| ----- | ---------------------------- | ------------------------------------------------------------------------------------------------ |
| 1     | Lint, format, typecheck      | `hogli verify --changed`, or `ruff check` and `pnpm --filter=@posthog/frontend typescript:check` |
| 2     | The nearest unit test        | `hogli test <file>`, `hogli test --changed`                                                      |
| 3     | Serializer and OpenAPI regen | `hogli up -d`, `hogli build:openapi`, then commit the generated diff                             |
| 4     | Storybook render             | `pnpm storybook`, open the affected story, compare before and after                              |
| 5     | The running stack            | `hogli up -d`, `hogli wait`, then exercise the flow                                              |
| 6     | Playwright or a recorded run | `hogli test playwright/<spec>.spec.ts` against a running stack                                   |

`hogli verify --changed` classifies the diff against master, runs layers 1 and 2, and lists any higher layer you still have to run yourself.
It does not report the diff as verified when a check was skipped, when a check only printed advice, or when no test covers the changed files.
mypy is one of those advice-only checks. It runs repo-wide, so `hogli verify` prints its command instead of running it.
Use `--plan` to see the classification without running anything.

## Decision table

| Change                     | Enough                                              | Wasted                                   |
| -------------------------- | --------------------------------------------------- | ---------------------------------------- |
| Pure logic, Python or TS   | 2: nearest unit test                                | 5: stack                                 |
| DRF serializer or viewset  | 3: OpenAPI regen, plus the endpoint test at layer 2 | 6: Playwright                            |
| Migration                  | 2: migration test, plus `hogli migrations:check`    | 4: Storybook                             |
| Kea logic                  | 2: logic test, plus typecheck                       | 4: Storybook                             |
| React component            | 4: Storybook render                                 | 5: stack, unless the data wiring changed |
| CSS only                   | 4: Storybook render                                 | 2: unit tests                            |
| CI workflow                | 1: `hogli lint:workflows`, `hogli ci:plan`          | 2: unit tests                            |
| SQL or HogQL               | 2: the ClickHouse-backed query test                 | 5: stack                                 |
| Docs or skills             | 1: format, `hogli lint:skills`                      | 2 and above                              |
| Django template            | 5: render the page in the running stack             | 6: Playwright                            |
| Settings, URLs, middleware | 5: running stack                                    | 6: Playwright                            |

A diff that mixes kinds needs the highest layer among them, and only for the files of that kind.

## Other rules still apply

- Reading the code does not confirm visual or UX work, as the root `AGENTS.md` says. A component or CSS change always needs at least a Storybook render.
- Layer 2 says where a test runs. Use `/writing-tests` to decide whether to add or change one. When a regression is hard to reach cheaply, extract the logic and test it at a lower layer.
- `hogli ci:preflight` stays the pre-push check, see `/running-ci-preflight`. `hogli verify` reuses its lint and format checks, so a pass here usually means a pass there too.

## When the stack is required

Start the stack only when the behavior spans more than one process and no layer 2 test runs both sides:

- Settings, URL routing, middleware, or the Content Security Policy, because only the browser applies them.
- A Django template, because only Django renders it.
- A change that a person has to see in the app: a new scene, a navigation change, or data flowing from ingestion to a UI.
- A Celery task, Temporal workflow, or plugin-server path whose wiring changed. A change to its logic alone stays at layer 2.
- A Playwright spec you changed, because it runs against the stack.

Everything else can skip the stack.
Django and ClickHouse-backed tests need the Postgres and ClickHouse services but not the web app, so `hogli up -d` plus a scoped `hogli test` still counts as layer 2.

## Report what you ran

Say which layer you stopped at and why the next one was not needed.
If you could not run a required layer, say so and name the command, so a reviewer knows what is unverified.
