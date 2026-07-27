/**
 * Per-agent models: two agents in the same cluster declare different
 * models strings. The runner resolves each through `resolveModel`, and the
 * resolved Model is what the driver streams with.
 *
 * `resolveModel` is the routing seam (called once per session in the worker),
 * so we record there and back it with the faux provider so each session
 * actually runs to completion.
 */

import { type AssistantMessage, fauxAssistantMessage, type Model, registerFauxProvider } from '@earendil-works/pi-ai'
import { Pool } from 'pg'

import { Worker } from '@posthog/agent-runner'
import {
    AgentSpecSchema,
    buildTestBundleStore,
    EMPTY_USAGE_TOTAL,
    HttpClient,
    InProcessSandboxPool,
    KafkaLogSink,
    newTestPrefix,
    PgApprovalStore,
    PgRevisionStore,
    PgSessionQueue,
    RedisSessionEventBus,
    SecretBroker,
    TEST_S3_BUCKET,
    wipeTestPrefix,
} from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

const KAFKA_HOSTS = process.env.KAFKA_HOSTS ?? 'localhost:9092'

type BundleTestStore = ReturnType<typeof buildTestBundleStore>

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'

let fauxHandle: ReturnType<typeof registerFauxProvider> | undefined

/**
 * Return a Model whose id is the spec string but whose `api` routes to the faux
 * provider, armed with a single completing response so the session finishes.
 */
function fauxModelFor(specModel: string): Model<string> {
    if (!fauxHandle) {
        fauxHandle = registerFauxProvider({ api: 'faux', provider: 'faux', models: [{ id: 'faux' }] })
    }
    fauxHandle.setResponses([fauxAssistantMessage(`from ${specModel}`, { stopReason: 'stop' }) as AssistantMessage])
    return { id: specModel, name: specModel, api: 'faux', provider: 'faux' } as unknown as Model<string>
}

describe('per-agent models resolution: real e2e', () => {
    let pool: Pool
    let bundlePrefix: string
    let bundleTestStore: BundleTestStore
    let bus: RedisSessionEventBus
    let logs: KafkaLogSink

    beforeAll(async () => {
        pool = new Pool({ connectionString: TEST_DB_URL })
        bus = new RedisSessionEventBus({
            url: REDIS_URL,
            channelPrefix: `permodel_${Math.random().toString(36).slice(2, 10)}`,
        })
        await bus.connect()
        logs = new KafkaLogSink({ brokers: KAFKA_HOSTS, topic: 'log_entries', name: 'permodel_test' })
        await logs.connect()
    })

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        bundlePrefix = newTestPrefix('agent_bundles_permodel_test')
        bundleTestStore = buildTestBundleStore(bundlePrefix)
    })

    afterEach(async () => {
        await wipeTestPrefix(bundleTestStore.client, bundlePrefix).catch(() => undefined)
        bundleTestStore.client.destroy()
    })

    afterAll(async () => {
        await bus.disconnect()
        await logs.disconnect()
        await pool.end()
    })

    it('two agents with different models values resolve distinct Models', async () => {
        const bundle = bundleTestStore.store
        const revisions = new PgRevisionStore(pool)
        const queue = new PgSessionQueue(pool)
        const modelsResolved: string[] = []

        const worker = new Worker({
            http: new HttpClient(),
            posthogApiBaseUrl: 'http://localhost:8010',
            logs,
            queue,
            revisions,
            bundle,
            sandboxes: new InProcessSandboxPool(),
            broker: new SecretBroker(),
            approvals: new PgApprovalStore(pool),
            bus,
            resolveSecrets: async () => ({}),
            // Per-agent model resolution — keys off models verbatim. This is
            // the seam the driver streams with, so recording here proves routing.
            resolveModel: (specModel) => {
                modelsResolved.push(specModel)
                return fauxModelFor(specModel)
            },
            maxConcurrency: 1,
        })

        // Two agents with distinct models strings.
        for (const [slug, model] of [
            ['agent-a', 'faux/model-A'],
            ['agent-b', 'faux/model-B'],
        ] as const) {
            const app = await revisions.createApplication({ team_id: 1, slug, name: slug, description: '' })
            const spec = AgentSpecSchema.parse({
                models: { mode: 'manual', models: [{ model }] },
                triggers: [
                    {
                        type: 'chat',
                        config: {},
                        auth: { modes: [{ type: 'public', acknowledge_public_exposure: true }] },
                    },
                ],
            })
            const rev = await revisions.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: `s3://${TEST_S3_BUCKET}/${bundlePrefix}/${app.id}/`,
                spec,
            })
            await bundle.write(rev.id, 'agent.md', 'x')
            const sha = await bundle.freeze(rev.id)
            await revisions.setRevisionState(rev.id, 'ready', sha)
            await revisions.setRevisionState(rev.id, 'live', sha)
            await revisions.setLiveRevision(app.id, rev.id)

            // Enqueue a session for this agent.
            await queue.enqueue({
                id: `00000000-0000-0000-0000-0000000000${slug === 'agent-a' ? 'a1' : 'b2'}`,
                application_id: app.id,
                revision_id: rev.id,
                team_id: 1,
                external_key: null,
                idempotency_key: null,
                trigger_metadata: null,
                state: 'queued',
                conversation: [{ role: 'user', content: 'go', timestamp: Date.now() }],
                pending_inputs: [],
                principal: null,
                retry_count: 0,
                usage_total: { ...EMPTY_USAGE_TOTAL },
                acl: [],
                pending_elevation_requests: [],
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            })
        }

        await worker.loop({ iterations: 2, claimTimeoutMs: 10 })

        // Both models should have been resolved exactly once each.
        expect(modelsResolved.sort()).toEqual(['faux/model-A', 'faux/model-B'])
    })
})
