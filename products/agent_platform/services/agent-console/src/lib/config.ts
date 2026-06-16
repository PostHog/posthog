/**
 * Typed config loader for the agent console.
 *
 * Every env var the console reads goes through this schema. Server route
 * handlers and lib code import `getConfig()` rather than reaching for
 * `process.env` directly — same pattern as the other agent services
 * (`agent-ingress/src/config.ts`, etc.).
 *
 * Dev (`NODE_ENV !== 'production'`) gets safe defaults so `pnpm dev`
 * works without any env setup — including a deterministic
 * `OAUTH_COOKIE_SECRET` so sessions survive `next dev` restarts. Prod
 * fails fast at boot if any required value is missing or malformed.
 */

import { z } from 'zod'

export function isDev(env: NodeJS.ProcessEnv = process.env): boolean {
    return env.NODE_ENV !== 'production'
}

// Deterministic 32+ char dev cookie sealer. Same approach as
// agent-shared's DEV_ENCRYPTION_KEY: a constant local default so
// devs aren't forced to copy a value into .env.local and so sealed
// cookies survive `next dev` restarts. **Never used in production** —
// the schema requires the env var to be set when NODE_ENV=production.
const DEV_OAUTH_COOKIE_SECRET = 'agent-console-dev-cookie-secret-do-not-use-in-prod'

// Matches the deterministic client_id Django's
// `setup_oauth_for_agent_console` always uses.
const DEV_OAUTH_CLIENT_ID = 'agent-console-dev'

const stripTrailingSlash = (v: string): string => v.replace(/\/$/, '')

export const AgentConsoleConfigSchema = z.object({
    posthogBaseUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:8010' : ''))
        .transform(stripTrailingSlash)
        .describe('PostHog Django base URL. Required in prod; dev defaults to http://localhost:8010.'),
    posthogAgentsBaseUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:3030' : ''))
        .transform(stripTrailingSlash)
        .describe('agent-ingress base URL. Required in prod; dev defaults to http://localhost:3030.'),
    agentIngressRoutingMode: z
        .enum(['path', 'domain'])
        .default('path')
        .describe(
            'Mirrors the ingress ROUTING_MODE. `path` (dev) forwards `/agents/<slug>/<route>` to the base URL as-is. ' +
                '`domain` (deployed, behind a wildcard cert) dials the agent`s public domain directly — ' +
                '`https://<slug><suffix>/<route>` — so the URL authority is the Host the domain-mode ingress resolves on ' +
                '(Host can`t be set on a fetch — it`s a forbidden header).'
        ),
    agentIngressDomainSuffix: z
        .string()
        .default('')
        .describe(
            'Host suffix for domain-mode routing (e.g. `.agents.dev.posthog.dev`). Required when routing mode is domain.'
        ),
    consoleBaseUrl: z
        .string()
        .url()
        .default('http://localhost:3040')
        .transform(stripTrailingSlash)
        .describe('Public URL the browser hits the console at. Used to build the OAuth redirect URI.'),
    oauthClientId: z
        .string()
        .default(() => (isDev() ? DEV_OAUTH_CLIENT_ID : ''))
        .describe(
            'OAuth client_id. Dev defaults to `agent-console-dev` (matches `python manage.py setup_oauth_for_agent_console`); prod supplied via ops.'
        ),
    oauthClientSecret: z
        .string()
        .default('')
        .describe(
            'OAuth client_secret. In dev, run `pnpm setup:local` to provision the app in Django and write this value into `.env.local`. Required in prod.'
        ),
    oauthCookieSecret: z
        .string()
        .default(() => (isDev() ? DEV_OAUTH_COOKIE_SECRET : ''))
        .describe(
            '32+ char string used to seal the HTTP-only session cookie. Dev defaults to a deterministic local key so sessions survive `next dev` restarts; prod must set explicitly.'
        ),
    nodeEnv: z
        .enum(['development', 'production', 'test'])
        .default('development')
        .describe('Node env. Controls cookie `secure` flag and the dev-default gating above.'),
    allowedTeamIds: z
        .string()
        // Dev convenience default only — `1,2` covers the first two projects in
        // a local install. In prod there is NO default: the operator must set
        // `AGENT_CONSOLE_ALLOWED_TEAM_IDS` explicitly (see the prod check in
        // `loadAgentConsoleConfig`) so a deployment can't silently ship the
        // `1,2` door, and so "run without a team gate" is a deliberate choice
        // (an explicit empty value) rather than an accident.
        .default(() => (isDev() ? '1,2' : ''))
        .transform((v) =>
            v
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean)
                .map((s) => Number(s))
                .filter((n) => Number.isInteger(n) && n > 0)
        )
        .describe(
            'Comma-separated PostHog team (project) IDs that may use this console deployment. Dev defaults to `1,2`; in prod it must be set explicitly. Set an empty string (`AGENT_CONSOLE_ALLOWED_TEAM_IDS=`) to deliberately run without a team gate. Checked at OAuth callback (cookie never gets set on denial) AND on every `/api/auth/me` refresh (an admin removing the team mid-session signs the user out on next refresh).'
        ),
})

export type AgentConsoleConfig = z.infer<typeof AgentConsoleConfigSchema>

const ENV_KEY_MAP: Record<string, keyof AgentConsoleConfig> = {
    POSTHOG_BASE_URL: 'posthogBaseUrl',
    POSTHOG_AGENTS_BASE: 'posthogAgentsBaseUrl',
    AGENT_INGRESS_ROUTING_MODE: 'agentIngressRoutingMode',
    AGENT_INGRESS_DOMAIN_SUFFIX: 'agentIngressDomainSuffix',
    CONSOLE_BASE_URL: 'consoleBaseUrl',
    POSTHOG_OAUTH_CLIENT_ID: 'oauthClientId',
    POSTHOG_OAUTH_CLIENT_SECRET: 'oauthClientSecret',
    OAUTH_COOKIE_SECRET: 'oauthCookieSecret',
    NODE_ENV: 'nodeEnv',
    AGENT_CONSOLE_ALLOWED_TEAM_IDS: 'allowedTeamIds',
}

// Fields with no safe prod default — empty values must fail closed at
// boot rather than silently producing broken behavior at request time.
const REQUIRED_IN_PROD: Array<keyof AgentConsoleConfig> = [
    'posthogBaseUrl',
    'posthogAgentsBaseUrl',
    'oauthClientId',
    'oauthClientSecret',
    'oauthCookieSecret',
]

const PROD_ENV_NAMES: Record<keyof AgentConsoleConfig, string> = {
    posthogBaseUrl: 'POSTHOG_BASE_URL',
    posthogAgentsBaseUrl: 'POSTHOG_AGENTS_BASE',
    agentIngressRoutingMode: 'AGENT_INGRESS_ROUTING_MODE',
    agentIngressDomainSuffix: 'AGENT_INGRESS_DOMAIN_SUFFIX',
    consoleBaseUrl: 'CONSOLE_BASE_URL',
    oauthClientId: 'POSTHOG_OAUTH_CLIENT_ID',
    oauthClientSecret: 'POSTHOG_OAUTH_CLIENT_SECRET',
    oauthCookieSecret: 'OAUTH_COOKIE_SECRET',
    nodeEnv: 'NODE_ENV',
    allowedTeamIds: 'AGENT_CONSOLE_ALLOWED_TEAM_IDS',
}

export function loadAgentConsoleConfig(env: NodeJS.ProcessEnv = process.env): AgentConsoleConfig {
    const raw: Record<string, string | undefined> = {}
    for (const [envName, schemaKey] of Object.entries(ENV_KEY_MAP)) {
        if (env[envName] !== undefined) {
            raw[schemaKey] = env[envName]
        }
    }
    const parsed = AgentConsoleConfigSchema.parse(raw)

    if (parsed.oauthCookieSecret && parsed.oauthCookieSecret.length < 32) {
        throw new Error('OAUTH_COOKIE_SECRET must be at least 32 characters')
    }

    if (parsed.nodeEnv === 'production') {
        const missing = REQUIRED_IN_PROD.filter((k) => !parsed[k])
        if (missing.length > 0) {
            const names = missing.map((k) => PROD_ENV_NAMES[k]).join(', ')
            throw new Error(`Missing required env vars in production: ${names}`)
        }
        // The team gate must be an explicit decision in prod: require the env
        // var to be present (even if empty) so we never silently ship the dev
        // `1,2` default or fall open by accident. An explicit empty value is a
        // deliberate opt-out of the gate.
        if (env.AGENT_CONSOLE_ALLOWED_TEAM_IDS === undefined) {
            throw new Error(
                'AGENT_CONSOLE_ALLOWED_TEAM_IDS must be set in production ' +
                    '(use an explicit empty value to run without a team gate)'
            )
        }
    }

    return parsed
}

let cached: AgentConsoleConfig | null = null

/**
 * Module-level singleton — loaded once per process. Route handlers and
 * lib modules call this instead of touching `process.env` themselves.
 */
export function getConfig(): AgentConsoleConfig {
    if (!cached) {
        cached = loadAgentConsoleConfig()
    }
    return cached
}

/** Test-only: reset the cached config so a follow-up `getConfig()` re-reads env. */
export function _resetConfigForTests(): void {
    cached = null
}
