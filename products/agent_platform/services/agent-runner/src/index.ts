/**
 * Worker entrypoint. Two Postgres pools:
 *
 *   - posthogDb (POSTHOG_DB_URL): the main Django/PostHog database, owns
 *     the *authoring* tables (agent_application, agent_revision). The
 *     runner reads from these via `PgRevisionStore`; never writes.
 *
 *   - agentDb (AGENT_DB_URL): the queue / runtime database, owns
 *     agent_session, agent_user, agent_sandbox_instance. Schema is
 *     Django-owned (migrations in products/agent_platform/backend/migrations/,
 *     applied in prod by the migrate_product_databases job); the runner
 *     is a pure client and never migrates.
 *
 * In dev / CI both env vars can point at the same Postgres; production
 * deploys them separately so high-churn runtime writes don't pressure the
 * main product DB.
 *
 * Run with `tsx src/index.ts` (no build step). `pnpm start` wraps that.
 */

import { S3Client } from '@aws-sdk/client-s3'
import { createServer } from 'node:http'

import {
    AnalyticsSink,
    analyticsDistinctId,
    createAgentPool,
    createLogger,
    DirectHttpClient,
    EncryptedEnvSecretResolver,
    EncryptedFields,
    createMetricsServer,
    handleMetricsRequest,
    HttpClient,
    HttpGatewayCatalog,
    HttpGatewayClient,
    initMetrics,
    installProcessHandlers,
    isDev,
    KafkaLogSink,
    MemoryStore,
    S3JsonlTabularStore,
    TabularStore,
    NoopAnalyticsSink,
    PgApprovalStore,
    PgCredentialBroker,
    PgIdentityCredentialStore,
    PgIdentityLinkStateStore,
    PgIdentityStore,
    PgMcpConnectionStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    PgTeamApiKeyResolver,
    RedisSessionEventBus,
    RoutingAnalyticsSink,
    S3BundleStore,
    S3MemoryStore,
    SecretBroker,
    selectSandboxPool,
    SlackFailureNotifier,
    TriggerAwareFailureNotifier,
} from '@posthog/agent-shared'
import { buildWebSearchProviders } from '@posthog/agent-tools'

import { defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'
import { posthogAiGatewayModel } from './models/ai-gateway-model'
import { resolveModelCached } from './models/pi-client'
import { makeEncryptedEnvResolver } from './resolvers/encrypted-env-resolver'
import { Worker } from './workers/worker'

const log = createLogger('agent-runner')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentRunnerConfig()

    // Prometheus: register Node process defaults. Prod runs a dedicated scrape
    // server on its own port (independent of /healthz). Dev mounts /metrics on
    // the health server instead (see below) — three services on one host can't
    // all bind the same dedicated port.
    initMetrics({ service: 'agent-runner' })
    const metricsServer = isDev() ? null : createMetricsServer({ port: config.metricsPort, log })

    // Fail-fast prod guard for the dev-only bearer attached to auth-less
    // external MCP refs. Prod must route auth via integrations or the
    // resolver-minted `kind: agent` path, not via a global bearer.
    if (config.devMcpBearerToken && !isDev()) {
        throw new Error(
            'AGENT_DEV_MCP_BEARER_TOKEN is a dev-only escape hatch for external-MCP auth and must not be set when NODE_ENV=production.'
        )
    }

    // Gateway path authenticates every call with one static phs_ bearer; without
    // it every request 401s, so fail fast rather than crash-loop at first turn.
    if (config.useAiGateway && !config.posthogAiGatewayKey) {
        throw new Error(
            'AGENT_USE_AI_GATEWAY requires POSTHOG_AI_GATEWAY_KEY — a phs_ project secret key with the llm_gateway:read scope.'
        )
    }

    // Outbound HTTP — every tool fetch, gateway fetch, and MCP transport
    // dispatches through here. In prod `config.httpsProxy` points at smokescreen
    // so author-supplied URLs (web-fetch, http-request, external MCPs) get SSRF
    // protection; required in prod, enforced at config-load (config.ts).
    const http = new HttpClient({ proxyUrl: config.httpsProxy })

    // `@posthog/web-search` provider chain. Built once from AGENT_WEB_SEARCH_*
    // config and threaded onto each session's ToolContext. The providers issue
    // their egress through the same proxy-bound `http` above (vendor hosts must
    // be on the smokescreen allowlist). Empty chain → the tool is gated out of
    // every session, so an unconfigured deployment never shows a tool that
    // just throws.
    const webSearchProviders = buildWebSearchProviders(
        {
            primary: config.webSearchProvider,
            fallbacks: config.webSearchFallbacks,
            keys: { exa: config.exaApiKey, tavily: config.tavilyApiKey, brave: config.braveApiKey },
        },
        log
    )
    log.info({ providers: webSearchProviders.map((p) => p.name) }, 'web_search.boot')

    // S3 bundle storage is required (enforced on `bundleS3Bucket` in config —
    // dev default, fail closed at config-load in prod). Endpoint is optional:
    // unset means "use the AWS SDK's regional default" (prod path); SeaweedFS in
    // dev sets it explicitly.
    const bundleS3 = new S3Client({
        endpoint: config.bundleS3Endpoint,
        region: config.bundleS3Region,
        forcePathStyle: config.bundleS3Endpoint ? config.bundleS3ForcePathStyle : false,
        credentials:
            config.bundleS3AccessKeyId && config.bundleS3SecretAccessKey
                ? {
                      accessKeyId: config.bundleS3AccessKeyId,
                      secretAccessKey: config.bundleS3SecretAccessKey,
                  }
                : undefined,
    })
    const bundles = new S3BundleStore({
        client: bundleS3,
        bucket: config.bundleS3Bucket,
        bucketPrefix: config.bundleS3Prefix,
    })

    const posthogDb = createAgentPool(config.posthogDbUrl)
    const agentDb = createAgentPool(config.agentDbUrl)
    // Schema is owned by `agent-migrator`; the chart runs a one-shot Job
    // (`charts/agent-migrator/`) on every sync. Runtime no longer calls
    // migrate() — runtime roles don't have DDL anyway, and racing N pods
    // to migrate was the source of today's pgmigrations CrashLoopBackOff.

    const defaultApiKey = defaultApiKeyFromConfig(config)
    const revisions = new PgRevisionStore(agentDb)

    // Encryption is required at boot now — constructor throws on empty
    // keys. Dev gets a deterministic default via `isDev()` in platform
    // config; prod must set ENCRYPTION_SALT_KEYS explicitly.
    const encryption = new EncryptedFields(config.encryptionSaltKeys)
    const resolveSecrets = makeEncryptedEnvResolver({ revisions, encryption })

    // Cross-process event bus. REDIS_URL is required — ingress /listen on host A
    // subscribes to events the runner publishes on host B via the same Redis.
    // Required in prod, enforced at config-load (config.ts).
    const bus = new RedisSessionEventBus({ url: config.redisUrl })
    await bus.connect()

    // Structured per-turn log sink. Every session lifecycle event the
    // runner emits is also shipped to the shared `log_entries` CH table
    // via Kafka, so the console's session-detail page can render them.
    // Connect at boot — failing here is louder than silently dropping
    // logs into a NoopLogSink in prod. Local dev: PostHog's flox env
    // brings up Kafka on `localhost:9092` by default.
    const logSink = new KafkaLogSink({
        brokers: config.kafkaHosts,
        logger: {
            info: (m, x) => log.info(x ?? {}, m),
            warn: (m, x) => log.warn(x ?? {}, m),
            error: (m, x) => log.error(x ?? {}, m),
        },
    })
    await logSink.connect()

    // Resolves a team's `phc_` project key from the main PostHog DB (cached per
    // team) for the LLM-analytics sink's per-team routing (below). The gateway
    // bearer is a single static phs_ now, so this no longer feeds it.
    const teamApiKeys = new PgTeamApiKeyResolver(posthogDb)

    // Shared MCP credentials (`spec.mcps[].connection`): reads/decrypts/refreshes
    // the native installation row. `http` is proxy-bound (refresh via smokescreen).
    // Needs UPDATE on `mcp_store_mcpserverinstallation` for write-back.
    const mcpConnections = new PgMcpConnectionStore(posthogDb, encryption, http)

    // LLM analytics sink. Captures `$ai_generation` per pi-ai call, `$ai_span`
    // per tool dispatch, and one `$ai_trace` per session via PostHog's standard
    // ingestion path (posthog-node /capture). Routes each event to the owning
    // team's OWN project (`team_id → phc_`), so agent traffic shows up natively
    // in that team's LLM Analytics with zero per-agent config; `phc_`-less teams
    // fall back to the global key. Every event carries
    // `$ai_origin: 'agent_platform_runner'` for the future signed-origin billing
    // filter.
    let analytics: AnalyticsSink = new NoopAnalyticsSink()
    if (config.posthogAnalyticsHost || config.posthogAnalyticsApiKey) {
        analytics = new RoutingAnalyticsSink({
            resolveApiKey: (teamId) => teamApiKeys.resolve(teamId),
            fallbackApiKey: config.posthogAnalyticsApiKey,
            host: config.posthogAnalyticsHost,
        })
    }

    // Principal → agent_user mapping the ingress writes through; consulted by
    // the runtime identity providers (spec.identity_providers).
    const identities = new PgIdentityStore(agentDb)
    // Persistent linked-credential store backing the runtime identity providers.
    const identityCredentials = new PgIdentityCredentialStore(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })
    // Gateway read client for /v1/usage + /v1/wallet/balance lookups.
    // ai-gateway is a cluster-internal service — use the direct client so the
    // call doesn't hit smokescreen (which would refuse it as RFC1918). The
    // proxy-bound `http` stays reserved for everything an agent author can
    // influence the URL of (tools, MCP, sandbox guest).
    const gatewayClient = config.useAiGateway
        ? new HttpGatewayClient({ baseUrl: config.aiGatewayUrl, http: new DirectHttpClient() })
        : null

    // Served-model catalog off the same gateway the data plane uses — source of
    // truth for models resolution + the models tool. DirectHttpClient:
    // cluster-internal, smokescreen would deny it.
    const gatewayCatalog = config.useAiGateway
        ? new HttpGatewayCatalog({
              baseUrl: config.aiGatewayUrl,
              bearer: config.posthogAiGatewayKey,
              http: new DirectHttpClient(),
          })
        : undefined

    // Agent memory: S3-backed file store. Required everywhere — the runner
    // refuses to boot without it so the `@posthog/memory-*` + `@posthog/table-*`
    // tools always work the same way in dev as in prod. Bucket + endpoint are
    // enforced in config (dev defaults via SeaweedFS / `hogli start`; fail closed
    // at config-load in prod).
    const memoryS3 = new S3Client({
        endpoint: config.memoryS3Endpoint,
        region: config.memoryS3Region,
        forcePathStyle: config.memoryS3ForcePathStyle,
        credentials:
            config.memoryS3AccessKeyId && config.memoryS3SecretAccessKey
                ? {
                      accessKeyId: config.memoryS3AccessKeyId,
                      secretAccessKey: config.memoryS3SecretAccessKey,
                  }
                : undefined,
    })
    const memoryStore: MemoryStore = new S3MemoryStore({
        client: memoryS3,
        bucket: config.memoryS3Bucket,
        bucketPrefix: config.memoryS3Prefix,
    })
    const tabularStore: TabularStore = new S3JsonlTabularStore({
        client: memoryS3,
        bucket: config.memoryS3Bucket,
        bucketPrefix: 'agent_tables',
    })
    log.info(
        { bucket: config.memoryS3Bucket, endpoint: config.memoryS3Endpoint, prefix: config.memoryS3Prefix },
        'memory.s3.enabled'
    )

    // Per-session credential broker — same shape ingress writes to.
    // Required for any non-public auth mode (e.g. the concierge's
    // oauth/pat). Construction throws if encryption isn't configured —
    // fail-fast at boot.
    const credentialBroker = new PgCredentialBroker(agentDb, {
        encryptionSaltKeys: config.encryptionSaltKeys,
    })

    // Approval-gated tools intercept dispatch before the real call, queue an
    // `agent_tool_approval_request` row, and resume after a janitor
    // /approvals/<id>/decide writes the decision. Without this wiring,
    // requires_approval flags on tools are silently ungated.
    const approvals = new PgApprovalStore(agentDb)

    // Out-of-band notifier for terminal failures. Slack-triggered sessions
    // get a sanitized thread reply when they crash before the agent can
    // post one itself; every other trigger type falls through to a no-op.
    // Uses the same encrypted_env resolver ingress uses for the signing
    // secret, so the bot token decrypts the same way at request time.
    const slackSecretResolver = new EncryptedEnvSecretResolver(encryption)
    const slackFailureNotifier = new SlackFailureNotifier({
        http,
        resolver: slackSecretResolver,
        logger: {
            warn: (meta, msg) => log.warn(meta, msg),
            info: (meta, msg) => log.info(meta, msg),
        },
    })
    const failureNotifier = new TriggerAwareFailureNotifier(
        { slack: slackFailureNotifier },
        { warn: (meta, msg) => log.warn(meta, msg) }
    )

    const worker = new Worker({
        queue: new PgSessionQueue(agentDb),
        revisions,
        bundle: bundles,
        sandboxes: selectSandboxPool({
            backend: config.sandboxBackend,
            sandboxHostImage: config.sandboxHostImage,
            sandboxDockerImage: config.sandboxDockerImage,
            sandboxModalImage: config.sandboxModalImage,
            modalAppName: config.modalAppName,
            modalRegion: config.modalRegion,
            sandboxOutboundCidrAllowlist: config.sandboxOutboundCidrAllowlist,
        }),
        sandboxInstances: new PgSandboxInstanceStore(agentDb),
        broker: new SecretBroker(),
        credentialBroker,
        approvals,
        // Clickable deep link that opens the approval in PostHog Code (the agent
        // console now lives in the desktop/web app). Surfaced to the model on a
        // gated tool call and whatever it posts to chat / Slack. Carries the
        // agent slug (`?agent=<slug>`) so the approval modal can address the
        // slug-routed ingress directly and decide under the user's own auth — no
        // project-scoped lookup. Handled by the `approval` deep-link key in
        // PostHog Code (posthog-code://approval/<id>?agent=<slug>).
        buildApprovalUrl: (requestId, slug) =>
            `${config.approvalLinkScheme}://approval/${requestId}${slug ? `?agent=${encodeURIComponent(slug)}` : ''}`,
        bus,
        logs: logSink,
        resolveSecrets,
        resolveModel: config.useAiGateway
            ? // Route every model through PostHog's ai-gateway as a drop-in proxy.
              // pi-ai picks the right api shape per provider; we override baseUrl
              // (per shape: openai keeps /v1, anthropic strips it) + provider tag.
              (specModel) =>
                  posthogAiGatewayModel({
                      specModel,
                      baseUrl: config.aiGatewayUrl,
                      // Non-null: boot guard above throws when useAiGateway && !posthogAiGatewayKey.
                      apiKey: config.posthogAiGatewayKey!,
                  })
            : undefined,
        gatewayCatalog,
        // Per-session bearer for pi-ai's `streamSimple` (no client-level default).
        // Gateway path → the static phs_ (cost bills to the team that owns it);
        // direct path → boot-time provider key (ANTHROPIC_API_KEY / OPENAI / etc).
        resolveApiKey: config.useAiGateway ? () => config.posthogAiGatewayKey : () => defaultApiKey,
        resolveGatewayHeaders: config.useAiGateway
            ? (session) => ({
                  'X-PostHog-Distinct-Id': analyticsDistinctId(session),
                  'X-PostHog-Trace-Id': session.id,
                  // Agent attribution onto the gateway's `$ai_generation` so the
                  // observability board can slice per agent. The gateway strips
                  // `$ai_*` from this passthrough but keeps `$agent_*`.
                  'X-PostHog-Properties': JSON.stringify({
                      $agent_application_id: session.application_id,
                      $agent_session_id: session.id,
                  }),
              })
            : undefined,
        // /v1/usage + /v1/wallet reads use the same static phs_ (the `phc` field
        // is the read client's bearer; key presence is guaranteed at boot above).
        resolveGatewayUsage: gatewayClient
            ? () => ({ client: gatewayClient, phc: config.posthogAiGatewayKey! })
            : undefined,
        // Gateway path: the gateway emits the `$ai_generation` (settled cost +
        // the attribution above), so the runner suppresses its own. Session-row
        // cost comes from /v1/usage post-turn (resolveGatewayUsage); pi-ai's
        // estimate is never used.
        gatewayEmitsGenerations: config.useAiGateway,
        analytics,
        maxConcurrency: config.maxConcurrency,
        maxOutputTokens: config.maxOutputTokens,
        memoryStore,
        tabularStore,
        // Per-principal identity linking (spec.identity_providers): reuse the
        // same agent DB + encryption the credential broker uses.
        identityCredentials,
        identityLinks: new PgIdentityLinkStateStore(agentDb),
        identities,
        linkRedirectBaseUrl: config.linkRedirectBaseUrl,
        mcpConnections,
        devMcpBearerToken: config.devMcpBearerToken,
        http,
        posthogApiBaseUrl: config.posthogApiBaseUrl,
        webSearchProviders,
        failureNotifier,
    })

    // Minimal liveness surface. The worker is queue-driven and has no request
    // path, so GET /healthz is the only thing on a port — 200 while running,
    // 503 once draining so k8s pulls a shutting-down pod out promptly.
    let healthy = true
    const devMetrics = isDev()
    const healthServer = createServer((req, res) => {
        // Dev: /metrics rides the health port (no dedicated scrape server).
        if (devMetrics && handleMetricsRequest(req, res, log)) {
            return
        }
        if (req.url === '/healthz') {
            res.writeHead(healthy ? 200 : 503, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ ok: healthy }))
            return
        }
        res.writeHead(404)
        res.end()
    })
    healthServer.listen(config.healthPort, () => log.info({ port: config.healthPort }, 'health server listening'))

    const shutdown = (sig: string): void => {
        log.info({ sig }, 'shutdown signal received — suspending in-flight sessions')
        healthy = false
        healthServer.close()
        metricsServer?.close()
        void worker.stop()
    }
    process.on('SIGTERM', () => shutdown('SIGTERM'))
    process.on('SIGINT', () => shutdown('SIGINT'))

    log.info(
        {
            posthogDb: config.posthogDbUrl,
            agentDb: config.agentDbUrl,
            concurrency: config.maxConcurrency,
            gateway: config.useAiGateway,
        },
        'starting worker loop'
    )
    await worker.loop()
    // Drain the analytics buffer BEFORE closing pools so the final batch of
    // `$ai_*` events lands in PostHog even on a rolling deploy.
    if (analytics instanceof RoutingAnalyticsSink) {
        await analytics.shutdown()
    }
    await logSink.disconnect()
    await Promise.all([posthogDb.end(), agentDb.end()])
    log.info({}, 'stopped cleanly')
}

// Silence unused-import warning while keeping resolveModelCached importable.
void resolveModelCached

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
