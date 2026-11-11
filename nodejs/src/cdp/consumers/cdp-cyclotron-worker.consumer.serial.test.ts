import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { randomUUID } from 'node:crypto'
import { AddressInfo, Server, Socket, connect, createServer } from 'node:net'
import { Pool } from 'pg'

import { createExampleInvocation, insertHogFunction, insertIntegration } from '~/cdp/_tests/fixtures'
import { CyclotronJobQueuePostgresV2 } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { PostgresIntegrationSource } from '~/cdp/services/managers/postgres-integration-source'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '~/cdp/types'
import { signIntegrationRef } from '~/cdp/utils/integration-input-refs'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

jest.setTimeout(60_000)

const RETURN_TWILIO_AUTH_TOKEN = ['_h', 32, 'auth_token', 32, 'twilio', 32, 'inputs', 1, 3, 38]
const FETCH_RETRIES = 3
const BACKOFF_MS = 2000

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

class IntegrationLookupFault {
    url = ''
    failing = false
    dropped = 0
    private readonly sockets = new Set<Socket>()
    private readonly server: Server = createServer((client) => this.forward(client))

    static async start(upstream: URL): Promise<IntegrationLookupFault> {
        const fault = new IntegrationLookupFault(upstream)
        await new Promise<void>((resolve) => fault.server.listen(0, '127.0.0.1', resolve))
        const url = new URL(upstream)
        url.host = `127.0.0.1:${(fault.server.address() as AddressInfo).port}`
        fault.url = url.toString()
        return fault
    }

    private constructor(private readonly upstream: URL) {}

    async close(): Promise<void> {
        for (const socket of this.sockets) {
            socket.destroy()
        }
        await new Promise((resolve) => this.server.close(resolve))
    }

    private forward(client: Socket): void {
        const upstream = connect(Number(this.upstream.port || 5432), this.upstream.hostname)
        for (const socket of [client, upstream]) {
            this.sockets.add(socket)
            socket.on('error', () => undefined)
            socket.on('close', () => {
                this.sockets.delete(socket)
                client.destroy()
                upstream.destroy()
            })
        }
        upstream.pipe(client)
        client.on('data', (chunk: Buffer) => {
            if (this.failing && chunk.toString('latin1').includes('fetchIntegrations')) {
                this.dropped++
                client.destroy()
                return
            }
            upstream.write(chunk)
        })
    }
}

type JobRow = { status: string; scheduled: Date; attempts: number | undefined }

describe('CdpCyclotronWorker on Cyclotron Postgres', () => {
    let hub: Hub
    let db: Pool
    let team: Team
    let queueName: string
    let fault: IntegrationLookupFault
    let integrationsDb: PostgresRouter
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
        fault = await IntegrationLookupFault.start(new URL(hub.DATABASE_URL))
        integrationsDb = new PostgresRouter({ ...hub, DATABASE_URL: fault.url, DATABASE_READONLY_URL: '' })
        producer = new HogQueueOfOneTest(queueName, hub)
        await producer.startAsProducer()
    })

    afterEach(async () => {
        fault.failing = false
        await worker?.stop()
        await producer.stopProducer()
        await integrationsDb.end()
        await fault.close()
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
            new PostgresIntegrationSource(integrationsDb, hub.encryptedFields)
        )
        worker = new CdpCyclotronWorker(
            config,
            { ...createCdpConsumerDeps(hub), integrationManager },
            new HogQueueOfOneTest(queueName, config),
            'hog'
        )
        await worker.start()
    }

    async function queueJobWithIntegrationRef(attempts: number): Promise<string> {
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
        invocation.state.attempts = attempts
        invocation.state.globals.inputs = {
            twilio: {
                $integration_ref: integration.id,
                $integration_ref_sig: signIntegrationRef(hub.encryptedFields, team.id, 'twilio', integration.id),
            },
        }
        await producer.queueInvocations([invocation])
        return invocation.id
    }

    async function jobRow(id: string): Promise<JobRow> {
        const { rows } = await db.query('SELECT status, scheduled, state FROM cyclotron_jobs WHERE id = $1', [id])
        const [row] = rows
        return {
            status: row.status,
            scheduled: new Date(row.scheduled),
            attempts: row.state ? parseJSON(row.state.toString()).state.attempts : undefined,
        }
    }

    it('retries a job whose integration lookup fails on a dropped connection, then completes it once the lookup recovers', async () => {
        const id = await queueJobWithIntegrationRef(0)
        fault.failing = true
        await startWorker()

        const retried = await waitForExpect(
            async () => {
                const row = await jobRow(id)
                expect(row).toMatchObject({ status: 'available', attempts: 1 })
                return row
            },
            15_000,
            50
        )
        expect(fault.dropped).toBeGreaterThan(0)
        expect(retried.scheduled.getTime()).toBeGreaterThan(Date.now())

        fault.failing = false

        await waitForExpect(async () => expect((await jobRow(id)).status).toBe('completed'), 15_000, 50)
    })

    it('fails a job once its integration lookup has used its last retry', async () => {
        const id = await queueJobWithIntegrationRef(FETCH_RETRIES - 1)
        fault.failing = true
        await startWorker()

        await waitForExpect(async () => expect((await jobRow(id)).status).toBe('failed'), 15_000, 50)
        expect(fault.dropped).toBeGreaterThan(0)
    })
})
