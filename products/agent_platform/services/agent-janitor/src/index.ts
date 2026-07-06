/**
 * Janitor entrypoint. Single-process: HTTP server + periodic sweep timer.
 *
 * One Postgres pool:
 *   - agentDb (AGENT_DB_URL): the Django-owned agent_platform product DB.
 *     Holds the authoring tables (agent_application + agent_revision, read by
 *     the revision store for /revisions/*) alongside the runtime queue +
 *     sandbox-instances the sweep reaps. Unlike the runner + ingress, the
 *     janitor never touches the main PostHog DB.
 *
 * Bundle storage: S3-backed via `S3BundleStore` (AGENT_BUNDLE_S3_BUCKET +
 * endpoint required at boot). Dev runs SeaweedFS; prod uses real S3 with the
 * pod's IRSA role for credentials. `FsBundleStore` is kept around for the
 * agent-tests harness only.
 *
 * Run via `tsx src/index.ts` (no precompile).
 */

import { S3Client } from '@aws-sdk/client-s3'

import {
    createAgentPool,
    createLogger,
    createMetricsServer,
    createModalSandboxTerminator,
    DirectHttpClient,
    HttpGatewayCatalog,
    initMetrics,
    installProcessHandlers,
    isDev,
    MemoryStore,
    MultiBackendSandboxTerminator,
    PgApprovalStore,
    PgIdentityAdminStore,
    PgRevisionStore,
    PgSandboxInstanceStore,
    PgSessionQueue,
    S3BundleStore,
    S3JsonlTabularStore,
    S3MemoryStore,
    TabularStore,
} from '@posthog/agent-shared'

import { loadAgentJanitorConfig } from './config'
import { cronTick, newCronTickState } from './cron-tick'
import * as metrics from './metrics'
import { buildJanitorApp } from './server'
import { sweepOnce } from './sweep'

const log = createLogger('agent-janitor')

async function main(): Promise<void> {
    installProcessHandlers(log)
    const config = loadAgentJanitorConfig()

    // Prometheus: Node process defaults. Prod runs a dedicated scrape server; the
    // sweep/cron metrics below let an alert catch a wedged singleton (rate of
    // *_runs_total → 0). Dev mounts /metrics on the request port inside
    // buildJanitorApp (no dedicated port — three services on one host collide).
    initMetrics({ service: 'agent-janitor' })
    if (!isDev()) {
        createMetricsServer({ port: config.metricsPort, log })
    }

    // S3 bundle storage is required (enforced on `bundleS3Bucket` in config —
    // dev default, fails closed at config-load in prod). Endpoint is optional:
    // unset means "use the AWS SDK's regional default" (prod path); SeaweedFS
    // in dev sets it explicitly.
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

    const agentDb = createAgentPool(config.agentDbUrl)
    // Schema is owned by Django (the agent_platform product DB, migrated by
    // migrate_product_databases). Runtime roles have no DDL.

    const queue = new PgSessionQueue(agentDb)
    const revisions = new PgRevisionStore(agentDb)
    // Approvals: backs both the /approvals/* HTTP surface (decide / list /
    // get for the authoring UI + MCP) and the sweep's expireQueued path.
    // Without it both 503 / silently no-op.
    const approvals = new PgApprovalStore(agentDb)
    // Sandbox-instance log + terminator for the reaper sweep. The
    // terminator's Modal client is constructed lazily inside the multi-
    // backend wrapper — janitors that never see a Modal row pay zero gRPC
    // startup cost. Requires MODAL_TOKEN_ID + MODAL_TOKEN_SECRET in env
    // (same secret_env entries the runner reads).
    const sandboxInstances = new PgSandboxInstanceStore(agentDb)
    const sandboxTerminator = new MultiBackendSandboxTerminator(createModalSandboxTerminator())
    // Keyless admin view over agent_user + agent_identity_credential for the
    // console "Users" pane. No decryption key — metadata only.
    const identityAdmin = new PgIdentityAdminStore(agentDb)

    const sweep = {
        queue,
        approvals,
        sandboxInstances,
        sandboxTerminator,
        stuckRunningThresholdMs: config.stuckRunningMs,
        stuckWaitingThresholdMs: config.stuckWaitingMs,
        idleCompletedThresholdMs: config.idleCompletedMs,
        idempotencyKeyTtlMs: config.idempotencyKeyTtlMs,
        maxRetries: config.maxRetries,
        sandboxStaleThresholdMs: config.sandboxStaleMs,
        // Pull idle completed candidates past the floor TTL; the sweep then
        // checks per-agent `spec.resume.max_completed_age_ms` before closing.
        listIdleCompletedCandidates: () => queue.listIdleCompleted(config.idleCompletedMs),
        // Per-agent TTL lookup — `spec.resume.max_completed_age_ms` defers
        // close for agents that opt in via spec.
        getResumeConfig: async (s: { revision_id: string }) => {
            const rev = await revisions.getRevision(s.revision_id)
            return rev?.spec?.resume
        },
    }
    // S3-backed memory store. Required everywhere — no optional fallback that
    // returns 503. Bucket + endpoint are enforced in config (dev defaults via
    // SeaweedFS / `hogli start`; fail closed at config-load in prod).
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

    // Served-model catalog off the same gateway the runner uses — validate +
    // freeze reject a models the gateway can't serve. DirectHttpClient:
    // cluster-internal, smokescreen would deny it.
    const gatewayCatalog = new HttpGatewayCatalog({
        baseUrl: config.aiGatewayUrl,
        bearer: config.posthogAiGatewayKey,
        http: new DirectHttpClient(),
    })

    const app = buildJanitorApp({
        queue,
        sweep,
        approvals,
        revisions,
        bundles,
        memoryStore,
        tabularStore,
        identityAdmin,
        gatewayCatalog,
        internalSigningKey: config.internalSigningKey,
    })
    app.listen(config.port, () => {
        log.info({ port: config.port }, 'listening')
    })

    // Cron tick state lives in-process — restart resets `lastTickAt`, the
    // catch-up policy handles missed firings, the unique index on
    // `(application_id, idempotency_key)` keeps two janitor replicas from
    // double-firing. See `cron-tick.ts` for the contract.
    const cronTickState = newCronTickState()
    const cronTickDeps = { revisions, queue }

    setInterval(async () => {
        // Sweep + cron tick run on the same interval but as independent
        // promises — a slow cron tick (cron-parser parsing a pathological
        // schedule, a slow listLiveCronRevisions roundtrip) doesn't starve
        // the sweep, and vice versa. Both wrap their own try/catch so a
        // single throw can't take the loop down.
        await Promise.all([
            (async () => {
                const end = metrics.sweepDuration.startTimer()
                try {
                    const result = await sweepOnce(sweep)
                    end()
                    metrics.sweepRuns.inc()
                    // Each action is its own series so a rising requeued/poisoned
                    // rate (runner instability) or sandbox_reap_failures (bad
                    // terminator) stands out on the dashboard.
                    for (const [action, count] of Object.entries(result)) {
                        if (count > 0) {
                            metrics.sweptTotal.labels({ action }).inc(count)
                        }
                    }
                    log.debug({ ...result }, 'sweep.done')
                } catch (err) {
                    end()
                    metrics.sweepFailures.inc()
                    log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'sweep.failed')
                }
            })(),
            (async () => {
                try {
                    const result = await cronTick(cronTickDeps, cronTickState)
                    metrics.cronRuns.inc()
                    if (result.fired > 0) {
                        metrics.cronFired.inc(result.fired)
                    }
                    if (result.errors > 0) {
                        metrics.cronErrors.inc(result.errors)
                    }
                    if (result.fired > 0 || result.errors > 0) {
                        log.info({ ...result }, 'cron_tick.done')
                    } else {
                        log.debug({ ...result }, 'cron_tick.done')
                    }
                } catch (err) {
                    metrics.cronFailures.inc()
                    log.error({ err: (err as Error).message, stack: (err as Error).stack }, 'cron_tick.failed')
                }
            })(),
            // Sample fleet queue depth once per tick. Own try/catch so a depth
            // query blip never marks the sweep failed. Zero-fill known states so
            // a state that empties shows 0 rather than freezing at its last value.
            (async () => {
                try {
                    const counts = await queue.countByState()
                    for (const state of metrics.KNOWN_SESSION_STATES) {
                        metrics.queueDepth.labels({ state }).set(counts[state] ?? 0)
                    }
                } catch (err) {
                    log.warn({ err: (err as Error).message }, 'queue_depth.sample_failed')
                }
            })(),
        ])
    }, config.sweepIntervalMs)
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main().catch((err) => {
        log.fatal({ err: (err as Error).message, stack: (err as Error).stack }, 'fatal')
        process.exit(1)
    })
}
