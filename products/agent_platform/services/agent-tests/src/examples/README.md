# examples — reference agent bundles + their regression tests

Self-contained agent bundles that demonstrate what's buildable on
the platform today.
They live under `agent-tests/` because the only deterministic
consumer is the e2e suite — each bundle has a corresponding
`cases/example-*.test.ts` that loads it from disk, deploys it
through the harness, and drives a realistic flow.

The bundles can also be deployed to a running platform (via the
authoring MCP or the janitor's revision API) — they're real
spec + bundle files, not test-only fixtures. The bundle's README
walks through the deploy steps. But the source of truth for
"does this still work" is the test case next to it.

| Bundle                                         | Test case                                                                                      | Status |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------- | ------ |
| [`sre-slack-bot/`](sre-slack-bot/)             | [`../cases/example-sre-bot.test.ts`](../cases/example-sre-bot.test.ts)                         | infant |
| [`wake-me-up/`](wake-me-up/)                   | [`../cases/example-wake-me-up.test.ts`](../cases/example-wake-me-up.test.ts)                   | infant |
| [`agent-approval-demo/`](agent-approval-demo/) | [`../cases/example-agent-approval-demo.test.ts`](../cases/example-agent-approval-demo.test.ts) | ready  |

"Infant" = buildable today against shipped primitives, but
some value loop is duct-taped because the platform doesn't have
the proper primitive yet. The bundle's README spells out which
gaps constrain it.

## Adding a new example

1. Pick an app
   whose prerequisites are mostly ✅.
2. Scaffold a subdirectory here with `spec.json` (the
   [`AgentSpec`](../../../agent-shared/src/spec/spec.ts) JSONB shape),
   `agent.md` (system prompt), `skills/*.md`, and a `README.md`
   that documents prereqs + deploy steps + known gaps.
3. Add a `../cases/example-<name>.test.ts` that loads the bundle
   from disk via `readFile`, deploys it through the harness, and
   runs a faux script through a realistic flow. This is the
   regression net for the bundle.
