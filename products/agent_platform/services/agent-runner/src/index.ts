/**
 * Worker entrypoint. Two Postgres pools:
 *
 *   - posthogDb (POSTHOG_DB_URL): the main Django/PostHog database, owns
 *     the *authoring* tables (agent_application, agent_revision). The
 *     runner reads from these via `PgRevisionStore`; never writes.
 *
 *   - agentDb (AGENT_DB_URL): the queue / runtime database, owns
 *     agent_session, agent_user, agent_sandbox_instance. Schema is
 *     managed by @posthog/agent-migrations; this entry applies any
 *     pending migrations on boot (idempotent).
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
    HttpClient,
    HttpGatewayClient,
    installProcessHandlers,
    isDev,
    KafkaLogSink,
    MemoryStore,
    S3JsonlTabularStore,
    TabularStore,
    NoopAnalyticsSink,
    PgApprovalStore,
    PgCredentialBroker,
    PgIdentityStore,
    PgIntegrationStore,
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

import { defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'
import { makePerAskerAuth } from './loop/per-asker-auth'
import { posthogAiGatewayModel } from './models/ai-gateway-model'
import { resolveModelCached } from './models/pi-client'
import { makeEncryptedEnvResolver } from './resolvers/encrypted-env-resolver'
import { makeIntegrationHostValidator } from './resolvers/integration-host-registry'
import { Worker } from './workers/worker'

const log = createLogger('agent-runner')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentRunnerConfig()

    // Fail-fast prod guard for the dev-only bearer attached to auth-less
    // external MCP refs. Prod must route auth via integrations or the
    // resolver-minted `kind: agent` path, not via a global bearer.
    if (config.devMcpBearerToken && !isDev()) {
        throw new Error(
            'AGENT_DEV_MCP_BEARER_TOKEN is a dev-only escape hatch for external-MCP auth and must not be set when NODE_ENV=production.'
        )
    }

    // Outbound HTTP — every tool fetch, gateway fetch, and MCP transport
    // dispatches through here. In prod `config.httpsProxy` points at smokescreen
    // so author-supplied URLs (web-fetch, http-request, external MCPs) get SSRF
    // protection; required in prod, enforced at config-load (config.ts).
    const http = new HttpClient({ proxyUrl: config.httpsProxy })

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

    // Integration credentials live in PostHog's existing `posthog_integration`
    // table (the same one Settings → Integrations writes to and HogFunctions
    // read from). Unconditionally wired now that encryption is required.
    const integrations = new PgIntegrationStore(posthogDb, encryption)
    const resolveIntegrations = async (session: {
        team_id: number
        revision_id: string
    }): Promise<Awaited<ReturnType<typeof integrations.resolveForSpec>>> => {
        const rev = await revisions.getRevision(session.revision_id)
        const kinds = rev?.spec?.integrations ?? []
        return integrations.resolveForSpec(session.team_id, kinds)
    }

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
    // team). Two consumers: the ai-gateway bearer (below) and the LLM-analytics
    // sink (next). Constructed unconditionally so analytics can route per-team
    // even when the gateway is off. See ai-gateway-integration.md §3 (W1).
    const teamApiKeys = new PgTeamApiKeyResolver(posthogDb)

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

    // Per-asker authorisation shortcut for approval-gated tools (#23 step 3).
    // Lets a Slack user who's already a team admin drive a gated tool
    // directly via chat instead of going through the queued-approval UI.
    // Reuses the same identity table the ingress writes through. Threaded
    // into `WorkerDeps.isAskerInApproverScope` → driver → gated tool's
    // pre-queue check in build-agent-tools.
    const identities = new PgIdentityStore(agentDb)
    const isAskerInApproverScope = makePerAskerAuth({ identities, posthogDb })
    // Gateway read client for /v1/usage + /v1/wallet/balance lookups.
    // ai-gateway is a cluster-internal service — use the direct client so the
    // call doesn't hit smokescreen (which would refuse it as RFC1918). The
    // proxy-bound `http` stays reserved for everything an agent author can
    // influence the URL of (tools, MCP, sandbox guest).
    const gatewayClient = config.useAiGateway
        ? new HttpGatewayClient({ baseUrl: config.aiGatewayUrl, http: new DirectHttpClient() })
        : null

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
        // gated tool call and whatever it posts to chat / Slack. The approval
        // request id alone resolves the approval in the fleet inbox, so the link
        // needs nothing more. Handled by the `approval` deep-link key in
        // PostHog Code (posthog-code://approval/<id>).
        buildApprovalUrl: (requestId) => `${config.approvalLinkScheme}://approval/${requestId}`,
        bus,
        logs: logSink,
        resolveIntegrations,
        resolveSecrets,
        resolveModel: config.useAiGateway
            ? // Route every model through PostHog's ai-gateway as a drop-in proxy.
              // pi-ai picks the right api shape per provider; we override baseUrl
              // (per shape: openai keeps /v1, anthropic strips it) + provider tag.
              (specModel) =>
                  posthogAiGatewayModel({
                      specModel,
                      baseUrl: config.aiGatewayUrl,
                  })
            : undefined,
        // The driver streams through pi-ai's `streamSimple`; the per-session
        // API key flows in here (no more client-level default). Gateway path
        // → resolve the owning team's `phc_`; direct path → fall back to the
        // boot-time default (ANTHROPIC_API_KEY / OPENAI_API_KEY / etc).
        resolveApiKey: config.useAiGateway ? (session) => teamApiKeys.resolve(session.team_id) : () => defaultApiKey,
        resolveGatewayHeaders: config.useAiGateway
            ? (session) => ({
                  'X-PostHog-Distinct-Id': analyticsDistinctId(session),
                  'X-PostHog-Trace-Id': session.id,
              })
            : undefined,
        resolveGatewayUsage: gatewayClient
            ? async (session) => ({ client: gatewayClient, phc: await teamApiKeys.resolve(session.team_id) })
            : undefined,
        // On the gateway path pi-ai's cost numbers are client-side estimates;
        // the gateway itself owns billing. We keep token counts. Cost is
        // recovered post-turn via /v1/usage/{request_id} (see resolveGatewayUsage).
        useGatewayCost: config.useAiGateway,
        analytics,
        maxConcurrency: config.maxConcurrency,
        maxOutputTokens: config.maxOutputTokens,
        memoryStore,
        tabularStore,
        isAskerInApproverScope,
        devMcpBearerToken: config.devMcpBearerToken,
        // Per-integration-kind host allowlist. Without this, any external MCP
        // ref with `auth.integration` fails closed at open with
        // `mcp_integration_host_validator_not_wired`. Registry seeded with
        // slack; extend in integration-host-registry.ts as kinds are added.
        integrationHostValidator: makeIntegrationHostValidator(),
        http,
        posthogApiBaseUrl: config.posthogApiBaseUrl,
        failureNotifier,
    })

    // Minimal liveness surface. The worker is queue-driven and has no request
    // path, so GET /healthz is the only thing on a port — 200 while running,
    // 503 once draining so k8s pulls a shutting-down pod out promptly.
    let healthy = true
    const healthServer = createServer((req, res) => {
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
