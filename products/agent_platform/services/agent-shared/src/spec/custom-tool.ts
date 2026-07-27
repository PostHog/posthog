/**
 * Author-facing contract for custom tools — user-written code an agent can
 * call, sandboxed in a Node process the platform spawns per session.
 *
 * **The sandbox is the security boundary.** The sandbox runs with no network
 * reach (`--network=none` in Docker, `blockNetwork:true` in Modal) and `ctx`
 * is deliberately minimal: a secret-nonce ref + a structured logger. There
 * is no `posthogApiBaseUrl` and no memory/table store access today. In v1 a
 * tool computes over its `args`, optionally consults secret nonces
 * (currently opaque — see note below), logs what it did, and returns
 * structured data the runner threads back to the model. What a tool can
 * reach is decided by the sandbox at runtime — the compile pipeline checks
 * shape, not reach.
 *
 * If an agent needs to call an external API today, use
 * `@posthog/http-request` (a native tool) with a secret pinned to
 * `allowed_hosts` in the spec. The direction of travel is a bridge —
 * `ctx.native(...)` / `ctx.mcp(...)` accessors that let a tool invoke
 * native tools and MCP connections from inside the sandbox — not yet
 * wired; see `docs/custom-tools.md`.
 *
 * **Secret nonces.** `ctx.secrets.ref(name)` returns an opaque per-session
 * nonce string declared in `spec.secrets[]`. The plaintext value never
 * enters the sandbox. Runner-side substitution of nonces at egress is not
 * yet wired (see `services/agent-sandbox-host/src/dispatch.js`), so a
 * returned nonce won't resolve to the real secret today — return values
 * for the runner to act on rather than attempting your own egress.
 *
 * **Authoring shape.** Custom tools are static object literals exported as
 * the file's default. The compile pipeline (see
 * `services/agent-janitor/src/compile-custom-tools.ts`) walks the AST to
 * confirm `export default { actions: { default: fn } }` before the source
 * ever runs. Use the `satisfies CustomTool` pattern below for editor
 * support — type-only imports are stripped at compile so nothing reaches
 * the sandbox runtime.
 *
 * @example
 *   import type { CustomTool, CustomToolContext } from '@posthog/agent-shared'
 *
 *   type Args = { name: string; count: number }
 *
 *   export default {
 *       actions: {
 *           default: async (args: Args, ctx: CustomToolContext) => {
 *               ctx.log('info', 'greeting', { name: args.name })
 *               return { greeting: `hi ${args.name} × ${args.count}` }
 *           },
 *       },
 *   } satisfies CustomTool
 */

// `Type`, `Static`, `TSchema` already flow through `@posthog/agent-shared` via
// the native-tool contract (`./tool`). Authors of custom tools import them
// from there, paired with the type-only declarations below.

/**
 * The `ctx` argument a custom-tool action receives at dispatch time.
 *
 * Mirrors the literal object built in `agent-sandbox-host/src/dispatch.js`'s
 * `buildContext` — keep this in lockstep with that file, since drift here
 * silently misleads tool authors about what's reachable in the sandbox.
 */
export interface CustomToolContext {
    /**
     * Per-session secret nonces declared in `spec.secrets[]`. Each `ref`
     * returns an opaque nonce string — the plaintext is never present in the
     * sandbox heap. Throws `secret not provisioned: <name>` if the name
     * isn't declared on the agent.
     */
    secrets: {
        ref(name: string): string
    }
    /**
     * Structured logger. Lines land in the sandbox container's stderr today;
     * ops can read them but the runner doesn't surface them in the session
     * conversation. Use for tracing your tool's internal decisions, not for
     * data the model needs to read — return data from `actions.default` for
     * that.
     */
    log(level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void
}

/**
 * Action signature for a custom tool. Receives validated args plus the
 * sandbox `ctx`, returns the result the runner threads back to the model.
 *
 * `args` type comes from the tool's TypeBox schema declared at PUT time
 * (`{description, args_schema, source}`); use `Static<typeof MySchema>` to
 * derive it on the author side.
 */
export type CustomToolAction<TArgs = unknown, TReturn = unknown> = (
    args: TArgs,
    ctx: CustomToolContext
) => TReturn | Promise<TReturn>

/**
 * The default-export shape every custom tool source must conform to.
 *
 * The runner always dispatches `action: "default"` today (see
 * `agent-runner/src/loop/build-agent-tools.ts`'s `makeCustomTool`), so
 * `actions.default` is the only entry the platform calls. Additional named
 * actions are allowed by the schema but unused at runtime — treat them as
 * helpers, not entry points.
 *
 * `id` is optional and informational; the binding id is set by the spec
 * entry (`spec.tools[].id`) when the tool is referenced from an agent.
 */
export interface CustomTool {
    id?: string
    actions: {
        default: CustomToolAction<unknown, unknown>
        [name: string]: CustomToolAction<unknown, unknown>
    }
}
