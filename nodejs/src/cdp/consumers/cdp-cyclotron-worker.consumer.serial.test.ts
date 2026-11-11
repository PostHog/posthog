import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

import { HOG_EXAMPLES } from '~/cdp/_tests/examples'
import { createExampleInvocation, insertHogFunction, insertIntegration } from '~/cdp/_tests/fixtures'
import { postgresThatDropsConnections } from '~/cdp/_tests/postgres-that-drops-connections'
import { HogInputsService } from '~/cdp/services/hog-inputs.service'
import { CyclotronJobQueuePostgresV2 } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { PostgresIntegrationSource } from '~/cdp/services/managers/postgres-integration-source'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '~/cdp/types'
import { signIntegrationRef } from '~/cdp/utils/integration-input-refs'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

jest.setTimeout(60_000)

const RETURN_TWILIO_AUTH_TOKEN = ['_h', 32, 'auth_token', 32, 'twilio', 32, 'inputs', 1, 3, 38]
const FETCH_RETRIES = 3
const BACKOFF_MS = 60_000

class HogQueueOfOneTest extends CyclotronJobQueuePostgresV2 {
    constructor(
        private readonly queueName: string,
        config: ConstructorParameters<typeof CyclotronJobQueuePostgresV2>[1]
    ) {
        super(10, config)
    }

    public override startAsConsumer(
        _queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ): Promise<void> {
        return super.startAsConsumer(this.queueName as CyclotronJobQueueKind, (invocations) =>
            consumeBatch(invocations.map((invocation) => ({ ...invocation, queue: 'hog' })))
        )
    }

    public override queueInvocations(invocations: CyclotronJobInvocation[]): Promise<void> {
        return super.queueInvocations(invocations.map((invocation) => this.onOwnQueue(invocation)))
    }

    public override queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        return super.queueInvocationResults(
            results.map((result) => ({ ...result, invocation: this.onOwnQueue(result.invocation) }))
        )
    }

    private onOwnQueue(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
        const queue = invocation.queue === 'hog' ? this.queueName : `${this.queueName}/${invocation.queue}`
        return { ...invocation, queue: queue as CyclotronJobQueueKind }
    }
}

type JobRow = { status: string; scheduled: Date }

describe('CdpCyclotronWorker on Cyclotron Postgres', () => {
    let hub: Hub
    let db: Pool
    let team: Team
    let queueName: string
    let lookupFails: boolean
    let droppedLookups: number
    let integrationsDb: { postgres: PostgresRouter; close: () => Promise<void> }
    let worker: CdpCyclotronWorker | undefined
    let producer: HogQueueOfOneTest

    beforeAll(async () => {
        hub = await createHub()
        db = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
    })

    afterAll(async () => {
        await db.end()
        await closeHub(hub)
    })

    beforeEach(async () => {
        queueName = `hog-worker-test-${randomUUID()}`
        worker = undefined
        team = (await createTestTeamFixture(hub.postgres)).team
        mockProducerObserver.resetKafkaProducer()
        mockFetch.mockClear()
        lookupFails = false
        droppedLookups = 0
        integrationsDb = await postgresThatDropsConnections(hub.DATABASE_URL, (message) => {
            const drops = lookupFails && message.toString('latin1').includes('fetchIntegrations')
            droppedLookups += drops ? 1 : 0
            return drops
        })
        producer = new HogQueueOfOneTest(queueName, hub)
        await producer.startAsProducer()
    })

    afterEach(async () => {
        lookupFails = false
        await worker?.stop()
        await producer.stopProducer()
        await integrationsDb.close()
        await db.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1 OR queue_name LIKE $2', [
            queueName,
            `${queueName}/%`,
        ])
    })

    async function startWorker(): Promise<void> {
        const config = {
            ...hub,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 10,
            CDP_FETCH_RETRIES: FETCH_RETRIES,
            CDP_FETCH_BACKOFF_BASE_MS: BACKOFF_MS,
            CDP_FETCH_BACKOFF_MAX_MS: BACKOFF_MS,
        }
        const integrationManager = new IntegrationManagerService(
            hub.pubSub,
            new PostgresIntegrationSource(integrationsDb.postgres, hub.encryptedFields)
        )
        worker = new CdpCyclotronWorker(
            config,
            { ...createCdpConsumerDeps(hub), integrationManager },
            new HogQueueOfOneTest(queueName, config),
            'hog'
        )
        await worker.start()
    }

    async function queueJobWithIntegrationRef(): Promise<string> {
        const integration = await insertIntegration(hub.postgres, team.id, {
            kind: 'oauth',
            config: { account_sid: 'AC-fake' },
            sensitive_config: { auth_token: hub.encryptedFields.encrypt('fake-auth-token-value') },
        })
        const hogFunction = await insertHogFunction(hub.postgres, team.id, {
            bytecode: RETURN_TWILIO_AUTH_TOKEN,
            inputs: { twilio: { value: integration.id } },
            inputs_schema: [{ key: 'twilio', type: 'integration', required: true }],
        })
        const invocation = createExampleInvocation(hogFunction)
        invocation.state.globals.inputs = {
            twilio: {
                $integration_ref: integration.id,
                $integration_ref_sig: signIntegrationRef(hub.encryptedFields, team.id, 'twilio', integration.id),
            },
        }
        await producer.queueInvocations([invocation])
        return invocation.id
    }

    async function queueFetchWithAccessToken(): Promise<string> {
        const integration = await insertIntegration(hub.postgres, team.id, {
            kind: 'oauth',
            config: {},
            sensitive_config: { access_token: hub.encryptedFields.encrypt('fake-access-token-value') },
        })
        const hogFunction = await insertHogFunction(hub.postgres, team.id, {
            ...HOG_EXAMPLES.simple_fetch,
            inputs: { oauth: { value: integration.id } },
            inputs_schema: [{ key: 'oauth', type: 'integration', required: true }],
        })
        const resolved = await new HogInputsService(
            hub.integrationManager,
            undefined,
            hub.encryptedFields
        ).loadIntegrationInputs(hogFunction)
        const invocation = createExampleInvocation(hogFunction)
        invocation.state.globals.inputs = {
            url: 'https://example.com/hook',
            method: 'POST',
            body: '{}',
            headers: { Authorization: `Bearer ${(resolved.oauth.value as Record<string, string>).access_token}` },
        }
        await producer.queueInvocations([invocation])
        return invocation.id
    }

    async function jobRow(id: string): Promise<JobRow> {
        const { rows } = await db.query('SELECT status, scheduled FROM cyclotron_jobs WHERE id = $1', [id])
        const [row] = rows
        return { status: row.status, scheduled: new Date(row.scheduled) }
    }

    it('retries a job whose integration lookup fails on a dropped connection, then completes it once the lookup recovers', async () => {
        const id = await queueJobWithIntegrationRef()
        lookupFails = true
        await startWorker()

        await waitForExpect(
            async () => {
                const row = await jobRow(id)
                expect(row.status).toBe('available')
                expect(row.scheduled.getTime()).toBeGreaterThan(Date.now() + BACKOFF_MS / 2)
            },
            15_000,
            50
        )
        expect(droppedLookups).toBeGreaterThan(0)

        lookupFails = false
        await db.query('UPDATE cyclotron_jobs SET scheduled = now() WHERE id = $1', [id])

        await waitForExpect(async () => expect((await jobRow(id)).status).toBe('completed'), 15_000, 50)
    })

    it('retries a fetch whose access token lookup fails on a dropped connection, then sends it with the token', async () => {
        const id = await queueFetchWithAccessToken()
        lookupFails = true
        await startWorker()

        await waitForExpect(
            async () => {
                const row = await jobRow(id)
                expect(row.status).toBe('available')
                expect(row.scheduled.getTime()).toBeGreaterThan(Date.now() + BACKOFF_MS / 2)
            },
            15_000,
            50
        )
        expect(droppedLookups).toBeGreaterThan(0)
        expect(mockFetch).not.toHaveBeenCalled()

        lookupFails = false
        await db.query('UPDATE cyclotron_jobs SET scheduled = now() WHERE id = $1', [id])

        await waitForExpect(async () => expect((await jobRow(id)).status).toBe('completed'), 15_000, 50)
        expect(mockFetch.mock.calls).toEqual([
            [
                'https://example.com/hook',
                expect.objectContaining({
                    headers: expect.objectContaining({ Authorization: 'Bearer fake-access-token-value' }),
                }),
            ],
        ])
    })

    it.each([
        ['its stored inputs', (): Promise<string> => queueJobWithIntegrationRef()],
        ['the access token of its fetch', (): Promise<string> => queueFetchWithAccessToken()],
    ])(
        'fails a job once the lookup of %s has used its last retry',
        async (_, queueJob) => {
            const id = await queueJob()
            lookupFails = true
            await startWorker()

            let reschedules = 0
            let status = ''
            while (status !== 'failed' && reschedules <= FETCH_RETRIES) {
                status = await waitForExpect(
                    async () => {
                        const row = await jobRow(id)
                        const rescheduled =
                            row.status === 'available' && row.scheduled.getTime() > Date.now() + BACKOFF_MS / 2
                        expect(rescheduled || row.status === 'failed').toBe(true)
                        return row.status
                    },
                    15_000,
                    50
                )
                if (status !== 'failed') {
                    reschedules++
                    await db.query('UPDATE cyclotron_jobs SET scheduled = now() WHERE id = $1', [id])
                }
            }

            expect({ reschedules, status }).toEqual({ reschedules: FETCH_RETRIES - 1, status: 'failed' })
            expect(mockFetch).not.toHaveBeenCalled()
        },
        60_000
    )
})
