# @posthog/harness

PostHog's [Pi](https://pi.dev) distribution.

It adds the PostHog LLM provider and the extensions in `src/extensions/` while keeping Pi's native runtime, sessions, tools, and RPC protocol.

## CLI

```bash
hog
hog /login
hog -p "Fix the tests" --model posthog/claude-opus-4-8
```

`harness` is an alias for `hog`.

## Runtime

```ts
import { createHarnessRuntime } from "@posthog/harness";

const runtime = await createHarnessRuntime({ cwd: "/workspace" });

await runtime.session.prompt("Fix the tests");
```

`createHarnessRuntime()` returns Pi's native `AgentSessionRuntime`.

## RPC

```ts
import { createHarnessRuntime, runRpcMode } from "@posthog/harness";

const runtime = await createHarnessRuntime({ cwd: "/workspace" });
await runRpcMode(runtime);
```

RPC is Pi's JSONL protocol over stdin/stdout. Harness does not define another protocol.

## Authentication

Run `hog /login`, or pass a PostHog personal API key:

```ts
const runtime = await createHarnessRuntime({ apiKey: "pha_…" });
```

Set `POSTHOG_REGION` to `us`, `eu`, or `dev` when needed.

## Public API

| Import | Purpose |
| --- | --- |
| `@posthog/harness` | Runtime creation and RPC mode |
| `@posthog/harness/runtime` | Runtime creation only |
| `@posthog/harness/extensions` | Harness extension registry |

Individual extensions are also exported under `@posthog/harness/extensions/*`.
