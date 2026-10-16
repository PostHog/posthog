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
| `@posthog/harness/extensions/context-wiki` | Context-wiki prompt and environment helpers |
| `@posthog/harness/extensions/enrichment` | File enrichment behavior |
| `@posthog/harness/extensions/task-system-prompt` | Task prompt builders and Pi task-prompt extension |
| `@posthog/harness/extensions/posthog-mcp-policy` | PostHog MCP permission policy and product-id classification |
| `@posthog/harness/extensions/local-tools` | Injected local tools (signed git, artifacts, peer messaging) and their PostHog task/run API client |
| `@posthog/harness/extensions/rtk` | RTK command-compression: Pi's native rewrite, the pure matching rules Claude's hook uses, and the Codex guidance text |
| `@posthog/harness/extensions/benjamin` | Vendored Benjamin-Plus and Simplified Technical English (ASD-STE100) system-prompt instructions, gated by `POSTHOG_BENJAMIN` |
| `@posthog/harness/extensions/agent-instructions` | Base appended system-prompt content (branch naming, PR links, plan mode, shell efficiency, spoken narration, …) |
| `@posthog/harness/extensions/skills-store` | PostHog skills-store pointer-file rendering and install/remove across Claude Code, Codex, and Pi skill roots |

Individual extensions are also exported under `@posthog/harness/extensions/*`.
