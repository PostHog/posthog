/**
 * Ingress entrypoint. Two Postgres pools (matching the runner):
 *
 *   - posthogDb (POSTHOG_DB_URL): Django-owned authoring tables. The ingress
 *     reads `agent_application` + `agent_revision` to resolve a request's
 *     slug/domain to a live revision.
 *
 *   - agentDb (AGENT_DB_URL): runtime queue. The ingress writes new
 *     `agent_session` rows when a trigger fires and reads / writes
 *     `agent_user` for identity resolution.
 *
 * Single-pool default (both env vars unset → same Postgres) is fine for dev.
 */

import {
    createAgentPool,
    createLogger,
    createMetricsServer,
    DirectHttpClient,
    EncryptedEnvSecretResolver,
    EncryptedFields,
    HttpClient,
    initMetrics,
    installProcessHandlers,
    isDev,
    PgCredentialBroker,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
    PgIdentityStore,
    PgApprovalStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
} from '@posthog/agent-shared'

import { loadAgentIngressConfig } from './config'
import { buildDefaultVerifiers, defaultPosthogIntrospector, type TeamOrgLookup } from './enqueue/verifiers'
import { buildApp } from './routing/server'

const log = createLogger('agent-ingress')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentIngressConfig()

    // Prometheus: Node process defaults. Prod runs a dedicated scrape server on
    // a separate port so /metrics is never exposed on the internet-facing
    // ingress listener. Dev mounts /metrics inside buildApp (no dedicated port —
    // three services on one host would collide); the dev request port isn't
    // public, so that's safe locally only.
    initMetrics({ service: 'agent-ingress' })
    if (!isDev()) {
        createMetricsServer({ port: config.metricsPort, log })
    }

    const posthogDb = createAgentPool(config.posthogDbUrl)
    const agentDb = createAgentPool(config.agentDbUrl)

    // REDIS_URL (cross-host /listen bus), HTTPS_PROXY (smokescreen — Slack
    // bot-token calls), and AGENT_INTERNAL_SIGNING_KEY (preview-token gate +
    // posthog_internal mode) are all required in prod and enforced at config-load
    // (config.ts: dev defaults, fail closed in prod) — no boot guards needed here.
    const bus = new RedisSessionEventBus({ url: config.redisUrl })
    await bus.connect()

    const http = new HttpClient({ proxyUrl: config.httpsProxy })

    // Backs the per-agent secret resolver below (Slack signing secret + bot
    // token from `encrypted_env`). Construction throws if encryption isn't
    // configured — fail-fast at boot rather than first request.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)

    // Per-mode auth verifiers. The introspector validates OAuth + PAT
    // bearers against PostHog's `/api/users/@me/` (covers both token
    // types). JWT verification needs an `issuer_secret_ref` resolver to
    // pull the embedding party's secret from the agent's encrypted env —
    // wired below.
    // PostHog's `/api/users/@me/` is cluster-internal — use the direct client
    // so the introspect doesn't hit smokescreen (which would refuse RFC1918).
    // The proxy-bound `http` stays reserved for everything an agent author can
    // influence the URL of (Slack identity bridge → slack.com).
    const introspector = defaultPosthogIntrospector({
        baseUrl: config.posthogApiBaseUrl,
        http: new DirectHttpClient(),
    })
    // Resolves an agent's owning org for `audience: 'organization'` gating. The
    // agent's team lives in the Django DB (`posthogDb`), a different database
    // than the revision store's `agentDb`, so we can't JOIN — a small lookup it
    // is. A team's org never changes, so the result is cached for the process
    // lifetime.
    const teamOrgCache = new Map<number, string | null>()
    const teamOrg: TeamOrgLookup = {
        async orgForTeam(teamId: number): Promise<string | null> {
            const cached = teamOrgCache.get(teamId)
            if (cached !== undefined) {
                return cached
            }
            const res = await posthogDb.query<{ organization_id: string | null }>(
                'SELECT organization_id FROM posthog_team WHERE id = $1',
                [teamId]
            )
            const org = res.rows[0]?.organization_id ?? null
            teamOrgCache.set(teamId, org)
            return org
        },
    }
    // Per-agent secret resolver. Decrypts the agent's `encrypted_env` and plucks
    // a named entry — backs the Slack signing-secret/bot-token lookups and the
    // shared_secret auth verifier (which reads `mode.secret_ref`).
    const secretResolver = new EncryptedEnvSecretResolver(encryption)
    const authProvider = {
        verifiers: buildDefaultVerifiers({
            introspector,
            teamOrg,
            jwtSecretResolver: secretResolver,
            sharedSecretResolver: secretResolver,
            internalSecret: config.internalSigningKey,
        }),
    }
    // Encrypted-at-rest credential broker (separate row per session,
    // Fernet-encrypted by the same EncryptedFields helper as
    // `AgentApplication.encrypted_env`). Required for any non-public
    // auth mode — construction throws if encryption isn't configured.
    const credentialBroker = new PgCredentialBroker(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })

    const app = buildApp({
        revisions: new PgRevisionStore(agentDb),
        queue: new PgSessionQueue(agentDb),
        identities: new PgIdentityStore(agentDb),
        // Backs the Slack principal-decision handler (decide + wake).
        approvals: new PgApprovalStore(agentDb),
        bus,
        routingMode: config.routingMode,
        domainSuffix: config.domainSuffix,
        pathPrefix: config.pathPrefix,
        publicBaseUrl: config.publicUrl,
        slackSigningSecretResolver: secretResolver,
        internalSigningKey: config.internalSigningKey,
        authProvider,
        credentialBroker,
        // Identity linking: the OAuth callback route consumes a link-state row,
        // rebuilds the provider from the app's spec + decrypted env, and persists.
        identityCredentials: new PgIdentityCredentialStore(agentDb, { encryptionSaltKeys: config.encryptionSaltKeys }),
        identityLinks: new PgIdentityLinkStateStore(agentDb),
        envEncryption: encryption,
        posthogApiBaseUrl: config.posthogApiBaseUrl,
        http,
    })
    app.listen(config.port, () => {
        log.info(
            {
                port: config.port,
                bus: bus.constructor.name,
                // Only surfaced when set — an unset public URL is normal (domain-mode
                // routes by host; Django builds callback URLs from its own settings).
                ...(config.publicUrl ? { public_url: config.publicUrl } : {}),
            },
            config.publicUrl ? `listening — reachable at ${config.publicUrl}` : 'listening'
        )
    })
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
