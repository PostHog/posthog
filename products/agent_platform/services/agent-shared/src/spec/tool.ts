/**
 * Native tool contract. Every tool exports these three:
 *   - id    : "@posthog/query" — versioned id; bumping creates a parallel tool
 *   - schema: declarative args/returns + requirements (description, cost hint)
 *   - run   : the actual call
 *
 * Schemas are TypeBox (the schema language pi-ai uses for tool parameters).
 * pi-ai passes the schema through to the model provider verbatim — no
 * zod→json-schema translation step.
 *
 * The runner imports tools by id, validates args via TypeBox's runtime
 * validator, and calls run() in-process. No sandbox for native tools.
 *
 * The authoring layer reads `schema` to know what tools exist and what each
 * one needs, so the wizard can compose a spec.
 */

import { Static, TSchema, Type } from 'typebox'

import type { MemoryStore } from '../memory/store'
import type { TabularStore } from '../memory/tabular-store'
import type { Credential } from '../runtime/credential-broker'
import type { HttpFetcher } from '../runtime/http-client'

export type { Static, TSchema }

export interface NativeToolSchema {
    description: string
    /** TypeBox schema. pi-ai accepts this natively as a Tool's `parameters`. */
    args: TSchema
    /** TypeBox schema for the return value (informational; not enforced at runtime today). */
    returns: TSchema
    /** Required integrations / scopes the team must have to use this tool. */
    requires: {
        integrations: string[]
        scopes: string[]
    }
    /** Hint for runner timeout selection + authoring UI cost annotations. */
    cost_hint: 'cheap' | 'medium' | 'expensive'
}

export interface ToolContext {
    /**
     * The agent's owning team — scopes agent-internal storage (memory, tables).
     * NOT used for PostHog data access; see `posthogUserTeamId`.
     */
    teamId: number
    /**
     * The team of the PostHog user who invoked this session (the incoming
     * `posthog` principal's team), or undefined when the caller didn't
     * authenticate as a PostHog user. The `@posthog/*` data tools act **as the
     * connected user** and target THIS team — never the agent's owning team —
     * so an agent can only read data the caller is authorized for. When
     * undefined those tools fail closed with `posthog_user_context_required`.
     */
    posthogUserTeamId?: number
    /** The agent (application) running this session — the memory scope key. */
    applicationId: string
    sessionId: string
    /** Resolved integration tokens, keyed by integration id ("slack:T01..."). */
    integrations: Record<string, IntegrationCredentials>
    /** Fetch resolved secret value for a name from spec.secrets. */
    secret(name: string): string | undefined
    /**
     * Per-secret host binding declared in `spec.secrets[]`. Returns:
     *   - `string[]` when the secret is the object form with `allowed_hosts`.
     *   - `null` when the secret is the bare-string form (declared but
     *     UNBOUND — `@posthog/http-request` refuses substitution).
     *   - `undefined` when the name isn't declared in `spec.secrets[]` at all.
     *
     * Fail-closed by design: the bare-string `null` return is the same shape
     * as `mcp-clients.ts` refusing an `auth.integration` ref when its host
     * validator isn't wired. Authors who want to call out to a service with
     * a secret MUST pin that secret to the destination host(s) — a prompt-
     * injected `${TOKEN}` against an attacker URL then refuses before fetch
     * rather than leaking the credential.
     */
    secretAllowedHosts(name: string): readonly string[] | null | undefined
    /** Structured log out of the tool — surfaces in the session log. */
    log(level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void
    /**
     * Optional bundle-file accessor scoped to the active revision. Tools that
     * need lazy access to skills/* or other bundle content (e.g.
     * `@posthog/load-skill`) read through this; tools that don't need bundle
     * access ignore it. Returns null when the file is missing.
     */
    readBundleFile?: (path: string) => Promise<string | null>
    /**
     * Available skills for this revision — `{ id, description, path }`.
     * Populated when `spec.skills` is non-empty. `@posthog/load-skill` uses
     * this to validate the requested skill id before fetching its body.
     */
    skillIndex?: ReadonlyArray<{ id: string; description?: string; path: string }>
    /**
     * S3-backed memory store, scoped at call time to the session's
     * (teamId, applicationId). Optional — when absent the memory tools
     * surface a 'memory_store_unavailable' error to the model. Wired in
     * the runner from AGENT_MEMORY_S3_* config; tests construct an
     * `InMemoryMemoryStore` directly.
     */
    memoryStore?: MemoryStore
    /**
     * Deterministic tabular store (seen-sets, append logs, simple queries),
     * scoped to (teamId, applicationId). Optional — when absent the
     * `@posthog/table-*` tools surface 'tabular_store_unavailable'. Wired in
     * the runner from the same S3 config as memory (agent_tables prefix).
     */
    tabularStore?: TabularStore
    /**
     * Resolve a per-session credential by target name. Set by ingress at
     * /run + /send (see `CredentialBroker`); returns null when the broker
     * isn't wired or the target isn't bound. Convention names:
     *   - `posthog_api` — bearer for calling PostHog APIs as the user
     *   - `self`        — raw auth proof + claims (jwt mode)
     */
    credentials?: {
        resolve(target: string): Promise<Credential | null>
    }
    /**
     * Outbound HTTP client. In prod this routes through smokescreen via
     * an undici ProxyAgent; in dev/test it's a direct fetch. **All tool
     * outbound HTTP must go through this** — Node's `fetch` does not
     * read HTTP_PROXY env vars, so bare `fetch(...)` calls silently
     * bypass smokescreen. See `HttpClient` in agent-shared/runtime.
     */
    http: HttpFetcher
    /**
     * Base URL for the PostHog API the `@posthog/agent-applications-*`
     * and other PostHog-proxying tools call against. Wired from
     * `config.posthogApiBaseUrl` at runner boot — no `process.env`
     * reads inside tool code.
     */
    posthogApiBaseUrl: string
}

export interface IntegrationCredentials {
    kind: string
    access_token: string
    refresh_token?: string
    metadata?: Record<string, unknown>
}

export interface NativeTool<TArgs = unknown, TReturn = unknown> {
    id: string
    schema: NativeToolSchema
    run(args: TArgs, ctx: ToolContext): Promise<TReturn>
}

/** Helper to author a tool with type-safe args/returns inferred from TypeBox. */
export function defineNativeTool<TArgsSchema extends TSchema, TReturnSchema extends TSchema>(def: {
    id: string
    description: string
    args: TArgsSchema
    returns: TReturnSchema
    requires?: Partial<NativeToolSchema['requires']>
    cost_hint?: NativeToolSchema['cost_hint']
    run: (args: Static<TArgsSchema>, ctx: ToolContext) => Promise<Static<TReturnSchema>>
}): NativeTool<Static<TArgsSchema>, Static<TReturnSchema>> {
    return {
        id: def.id,
        schema: {
            description: def.description,
            args: def.args,
            returns: def.returns,
            requires: {
                integrations: def.requires?.integrations ?? [],
                scopes: def.requires?.scopes ?? [],
            },
            cost_hint: def.cost_hint ?? 'medium',
        },
        run: def.run,
    }
}

/** Re-export TypeBox `Type` so tool authors have one import. */
export { Type }
