import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { SESv2Client } from '@aws-sdk/client-sesv2'
import { DateTime } from 'luxon'
import { randomUUID } from 'node:crypto'
import { AddressInfo, Socket, connect, createServer } from 'node:net'
import { Client, Pool } from 'pg'
import { Histogram, register } from 'prom-client'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import {
    BucketProxy,
    StoredFile,
    attachmentStoreConfig,
    deliveredTo,
    sesClientFor,
    uploadAttachment,
} from '~/cdp/_tests/email-delivery-fakes'
import { FakeSes, startFakeSes } from '~/cdp/_tests/fake-ses'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { CyclotronV2Manager } from '~/cdp/services/cyclotron-v2'
import { createHogFlowInvocation } from '~/cdp/services/hogflows/hogflow-executor.service'
import { TRANSACTIONAL_EMAIL_EVENT } from '~/cdp/services/hogflows/hogflow-sensitivity'
import { CONSUMER_STOP_DEADLINE_MS, CyclotronJobQueuePostgresV2 } from '~/cdp/services/job-queue/job-queue-postgres-v2'
import { LONGEST_WAIT_FOR_ROOM_MS } from '~/cdp/services/messaging/attachment-horizon'
import {
    InFlightLimits,
    InFlightRegistry,
    LARGEST_SEND_FILE_BYTES,
    estimateSend,
} from '~/cdp/services/messaging/in-flight-registry'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils/hog-function-filtering'
import { KAFKA_EMAIL_STATUS } from '~/common/config/kafka-topics'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { CdpCyclotronWorkerEmail, RESULT_WRITE_MARGIN_MS } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(60_000)

jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: () => Promise.resolve([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: () => Promise.resolve(['192.0.2.1']),
        resolve6: () => Promise.resolve([]),
    })),
}))

class EmailQueueOfOneTest extends CyclotronJobQueuePostgresV2 {
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
            consumeBatch(invocations.map((invocation) => ({ ...invocation, queue: 'email' })))
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
        const queue = invocation.queue === 'email' ? this.queueName : `${this.queueName}/${invocation.queue}`
        return { ...invocation, queue: queue as CyclotronJobQueueKind }
    }
}

type HeldQuery = { release: () => void; drop: () => void }

const SSL_REQUEST = 80877103
const GSS_ENCRYPTION_REQUEST = 80877104
const ENDS_A_REQUEST = new Set(['S', 'Q', 'X', 'p', 'H', 'c', 'f'])

class CyclotronProxy {
    url = ''
    private readonly waiting: { matches: (request: string) => boolean; caught: (held: HeldQuery) => void }[] = []
    private readonly holding = new Set<HeldQuery>()
    private readonly sockets = new Set<Socket>()
    private readonly server = createServer((client) => this.forward(client))

    static async start(upstream: URL): Promise<CyclotronProxy> {
        const proxy = new CyclotronProxy(upstream)
        await new Promise<void>((resolve) => proxy.server.listen(0, '127.0.0.1', resolve))
        const url = new URL(upstream)
        url.host = `127.0.0.1:${(proxy.server.address() as AddressInfo).port}`
        proxy.url = url.toString()
        return proxy
    }

    private constructor(private readonly upstream: URL) {}

    hold(matches: (request: string) => boolean): Promise<HeldQuery> {
        return new Promise((caught) => this.waiting.push({ matches, caught }))
    }

    releaseAll(): void {
        this.waiting.splice(0)
        for (const held of this.holding) {
            held.release()
        }
    }

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
                client.destroy()
                upstream.destroy()
            })
        }
        upstream.pipe(client)

        let unread = Buffer.alloc(0)
        let request: Buffer[] = []
        let startedUp = false
        let paused = false
        const forwardRequests = (): void => {
            while (!paused) {
                const typeBytes = startedUp ? 1 : 0
                if (unread.length < typeBytes + 4) {
                    return
                }
                const length = typeBytes + unread.readInt32BE(typeBytes)
                if (unread.length < length) {
                    return
                }
                const message = unread.subarray(0, length)
                unread = unread.subarray(length)
                if (!startedUp) {
                    const code = message.readInt32BE(4)
                    startedUp = code !== SSL_REQUEST && code !== GSS_ENCRYPTION_REQUEST
                    upstream.write(message)
                    continue
                }
                request.push(message)
                if (!ENDS_A_REQUEST.has(String.fromCharCode(message[0]))) {
                    continue
                }
                const whole = Buffer.concat(request)
                request = []
                const index = this.waiting.findIndex(({ matches }) => matches(whole.toString('latin1')))
                if (index === -1) {
                    upstream.write(whole)
                    continue
                }
                const [{ caught }] = this.waiting.splice(index, 1)
                paused = true
                const held: HeldQuery = {
                    release: () => {
                        this.holding.delete(held)
                        upstream.write(whole)
                        paused = false
                        forwardRequests()
                    },
                    drop: () => {
                        this.holding.delete(held)
                        client.destroy()
                    },
                }
                this.holding.add(held)
                caught(held)
            }
        }
        client.on('data', (chunk: Buffer) => {
            unread = Buffer.concat([unread, chunk])
            forwardRequests()
        })
    }
}

const completes = (request: string): boolean => request.includes("SET status = 'completed'")
const fails = (request: string): boolean => request.includes("SET status = 'failed'")
const dequeues = (request: string): boolean => request.includes("SET status = 'running'")
const defers = (request: string): boolean => request.includes('dequeue_seq = COALESCE')
const writeOf =
    (write: (request: string) => boolean, id: string) =>
    (request: string): boolean =>
        write(request) && request.includes(id)

async function metric(name: string, labels: Record<string, string> = {}): Promise<number> {
    const samples = (await register.getSingleMetric(name)?.get())?.values ?? []
    return samples
        .filter((sample) => Object.entries(labels).every(([key, value]) => sample.labels[key] === value))
        .reduce((sum, sample) => sum + sample.value, 0)
}

async function batchPhasesEnded(phase: 'invocations' | 'background'): Promise<number> {
    const name = 'cdp_cyclotron_worker_phase_duration_seconds'
    const samples = (await (register.getSingleMetric(name) as Histogram | undefined)?.get())?.values ?? []
    return samples
        .filter((sample) => sample.metricName === `${name}_count` && sample.labels.phase === phase)
        .reduce((sum, sample) => sum + sample.value, 0)
}

const POLL_DELAY_MS = 10

type JobRow = { status: string; scheduled: Date; lease: bigint | null; queueMetadata: Record<string, any> | undefined }
type EmailStatus = { status: string; reason: string; sendingDomain: string }

describe('CdpCyclotronWorkerEmail on Cyclotron Postgres', () => {
    let hub: Hub
    let db: Pool
    let team: Team
    let hogFlow: HogFlow
    let queueName: string
    let recipient: string
    let ses: FakeSes
    let bucket: BucketProxy
    let cyclotron: CyclotronProxy
    let workers: CdpCyclotronWorkerEmail[]
    let producer: EmailQueueOfOneTest
    let invoice: StoredFile
    let integration: { id: number }
    let template: { template_id: string }
    let backToRealClock: () => void = () => undefined
    let posthogDb: Pool
    let workflowTableHolders: Client[]
    let routers: PostgresRouter[]

    const roomFor = (sends: number): InFlightLimits => ({
        budgetBytes: sends * estimateSend(invoice.metadata.sizeBytes).reservedBytes,
        heapLimitBytes: 64 * 1024 * 1024 * 1024,
        maxInFlight: 100,
    })

    beforeAll(async () => {
        hub = await createHub()
        db = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
        posthogDb = new Pool({ connectionString: hub.DATABASE_URL })
    })

    afterAll(async () => {
        await Promise.all([db.end(), posthogDb.end()])
        await closeHub(hub)
    })

    beforeEach(async () => {
        queueName = `email-worker-test-${randomUUID()}`
        recipient = `${randomUUID()}@example.com`
        workers = []
        workflowTableHolders = []
        routers = []
        team = (await createTestTeamFixture(hub.postgres)).team
        ses = await startFakeSes({
            [hub.SES_TRACKED_CONFIGURATION_SET]: { tracking: true },
            [hub.SES_UNTRACKED_CONFIGURATION_SET]: { tracking: false },
        })
        bucket = await BucketProxy.start()
        cyclotron = await CyclotronProxy.start(new URL(hub.CYCLOTRON_NODE_DATABASE_URL!))
        mockProducerObserver.resetKafkaProducer()

        integration = await insertIntegration(hub.postgres, team.id, {
            id: team.id,
            kind: 'email',
            config: {
                email: 'sender@posthog-test.com',
                name: 'Sender',
                domain: 'posthog-test.com',
                verified: true,
                provider: 'ses',
            },
        })
        template = await insertHogFunctionTemplate(hub.postgres, {
            id: `template-email-worker-test-${team.id}`,
            name: 'Email worker test',
            code: 'sendEmail(inputs.email)',
            inputs_schema: [
                {
                    type: 'native_email',
                    key: 'email',
                    label: 'Email message',
                    integration: 'email',
                    required: true,
                    secret: false,
                    description: '',
                    templating: 'liquid',
                },
            ],
        })
        hogFlow = await insertEmailFlow()
        invoice = await uploadAttachment(team.id, { filename: 'invoice.pdf', contentType: 'application/pdf' })
        producer = new EmailQueueOfOneTest(queueName, hub)
        await producer.startAsProducer()
    })

    afterEach(async () => {
        backToRealClock()
        await Promise.all(workflowTableHolders.map((holder) => holder.end()))
        cyclotron.releaseAll()
        bucket.release('refuse')
        await Promise.all(workers.map((worker) => worker.stop()))
        await Promise.all(routers.map((router) => router.end()))
        await producer.stopProducer()
        await Promise.all([bucket.close(), ses.close(), cyclotron.close()])
        await db.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1 OR queue_name LIKE $2', [
            queueName,
            `${queueName}/%`,
        ])
    })

    function emailFlow(
        delayAfterEmail?: string,
        stepAfterDelay: 'exit' | 'function_email' | 'function' = 'exit',
        firstStep: 'function_email' | 'function' = 'function_email'
    ): HogFlow {
        const emailStep = {
            type: 'function_email',
            config: {
                template_id: template.template_id,
                inputs: {
                    email: {
                        value: {
                            to: { email: recipient, name: 'Recipient' },
                            from: { integrationId: integration.id, email: 'sender@posthog-test.com' },
                            subject: 'Your invoice',
                            text: 'Your invoice is attached.',
                            html: '<p>Your invoice is attached.</p>',
                        },
                    },
                },
            },
        }
        const emailAfterDelay = stepAfterDelay !== 'exit'
        const afterDelay = emailAfterDelay ? 'next_email' : 'exit'
        return new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withStatus('active')
            .withWorkflow({
                actions: {
                    trigger: { type: 'trigger', config: { type: 'api' } },
                    email: { ...emailStep, type: firstStep },
                    ...(delayAfterEmail && {
                        delay: { type: 'delay', config: { delay_duration: delayAfterEmail } },
                    }),
                    ...(emailAfterDelay && { next_email: { ...emailStep, type: stepAfterDelay } }),
                    exit: { type: 'exit', config: {} },
                },
                edges: [
                    { from: 'trigger', to: 'email', type: 'continue' },
                    { from: 'email', to: delayAfterEmail ? 'delay' : 'exit', type: 'continue' },
                    ...(delayAfterEmail ? [{ from: 'delay', to: afterDelay, type: 'continue' }] : []),
                    ...(emailAfterDelay ? [{ from: 'next_email', to: 'exit', type: 'continue' }] : []),
                ],
            } as any)
            .build()
    }

    const insertEmailFlow = (...shape: Parameters<typeof emailFlow>): Promise<HogFlow> =>
        insertHogFlow(hub.postgres, emailFlow(...shape))

    async function startWorker(
        limits: InFlightLimits | null,
        sesClient: SESv2Client = sesClientFor(ses),
        postgres: PostgresRouter = hub.postgres
    ): Promise<CdpCyclotronWorkerEmail> {
        const config = {
            ...hub,
            CYCLOTRON_NODE_DATABASE_URL: cyclotron.url,
            CDP_CYCLOTRON_BATCH_DELAY_MS: POLL_DELAY_MS,
            CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: 50,
            CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: bucket.endpoint,
            CDP_EMAIL_ATTACHMENTS_S3_PREFIX: attachmentStoreConfig.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
            EMAIL_STATUS_ENABLED: true,
        }
        const worker = new CdpCyclotronWorkerEmail(
            config,
            { ...createCdpConsumerDeps(hub), postgres },
            new EmailQueueOfOneTest(queueName, config),
            new InFlightRegistry(limits, () => 0)
        )
        worker.emailService.sesV2Client = sesClient
        workers.push(worker)
        await worker.start()
        return worker
    }

    function transactionalSend(
        files: StoredFile['metadata'][] | null,
        overrides: Partial<CyclotronJobInvocation> = {}
    ): CyclotronJobInvocation {
        const event = {
            uuid: new UUIDT().toString(),
            event: TRANSACTIONAL_EMAIL_EVENT,
            distinct_id: recipient,
            timestamp: DateTime.now().toISO(),
            url: '',
            properties: { to: recipient },
            elements_chain: '',
        }
        const invocation = createHogFlowInvocation(
            { event, project: { id: team.id, name: team.name, url: '' }, variables: {} } as any,
            hogFlow,
            convertToHogFunctionFilterGlobal({ event, person: undefined, groups: {}, variables: {} } as any)
        )
        invocation.state.send = {
            tracking: { captureEngagement: false },
            ...(files && { attachments: files }),
        }
        return { ...invocation, queue: 'email', queuePriority: 0, ...overrides }
    }

    async function enqueue(...sends: CyclotronJobInvocation[]): Promise<string[]> {
        await producer.queueInvocations(sends)
        return sends.map(({ id }) => id)
    }

    async function jobRow(id: string): Promise<JobRow> {
        const { rows } = await db.query(
            `SELECT status, scheduled, state,
                    (extract(epoch FROM last_heartbeat) * 1000000)::bigint::text AS lease
             FROM cyclotron_jobs WHERE id = $1`,
            [id]
        )
        const [row] = rows
        return {
            status: row.status,
            scheduled: new Date(row.scheduled),
            lease: row.lease === null ? null : BigInt(row.lease),
            queueMetadata: row.state ? parseJSON(row.state.toString()).queueMetadata : undefined,
        }
    }

    const ended = (id: string, timeoutMs = 10_000): Promise<string> =>
        waitForExpect(
            async () => {
                const { status } = await jobRow(id)
                expect(['completed', 'failed', 'canceled']).toContain(status)
                return status
            },
            timeoutMs,
            50
        )

    const deferredRow = (id: string, attachmentDeferrals: number): Promise<JobRow> =>
        waitForExpect(async () => {
            const row = await jobRow(id)
            expect(row.status).toBe('available')
            expect(row.queueMetadata?.attachmentDeferrals).toBe(attachmentDeferrals)
            return row
        })

    const delivered = (): string[][] =>
        deliveredTo(ses, recipient).map((email) => email.attachments.map((file) => file.filename))

    const emailStatusOf = (id: string): EmailStatus | undefined => {
        const rows = mockProducerObserver
            .getProducedKafkaMessagesForTopic(KAFKA_EMAIL_STATUS)
            .map((message) => message.value as Record<string, any>)
            .filter((row) => row.message_id === id)
        const latest = rows.reduce<Record<string, any> | undefined>(
            (top, row) => (!top || BigInt(row.version) > BigInt(top.version) ? row : top),
            undefined
        )
        return latest && { status: latest.status, reason: latest.reason, sendingDomain: latest.sending_domain }
    }

    it('writes the plain sends of a batch and dequeues the next one while a send with files waits on its download', async () => {
        bucket.answer = 'hold'
        const [withFiles, plain] = await enqueue(transactionalSend([invoice.metadata]), transactionalSend(null))
        await startWorker(roomFor(1))

        expect(await ended(plain)).toBe('completed')
        const [later] = await enqueue(transactionalSend(null))
        expect(await ended(later)).toBe('completed')
        expect(delivered()).toEqual([[], []])
        expect((await jobRow(withFiles)).status).toBe('running')

        bucket.release()
        expect(await ended(withFiles)).toBe('completed')
        expect(delivered()).toEqual([[], [], ['invoice.pdf']])
    })

    it.each([
        {
            download: 'is served',
            release: 'pass' as const,
            status: 'completed',
            queueMetadata: null,
            inbox: [['invoice.pdf']],
        },
        {
            download: 'is refused, so it retries the load',
            release: 'refuse' as const,
            status: 'available',
            queueMetadata: (firstDueAt: number) => ({ attachmentDueAt: firstDueAt, attachmentLoadRetries: 1 }),
            inbox: [],
        },
    ])(
        'defers the sends it has no room for, with one more deferral, a longer delay and the first due time, and runs an admitted one whose download $download, keeping its first due time',
        async ({ release, status, queueMetadata, inbox }) => {
            const firstDueAt = Date.now() - 60_000
            const scheduledFirst = DateTime.fromMillis(Date.now() - 30_000)
            bucket.answer = 'hold'
            await startWorker(roomFor(1))
            const [running] = await enqueue(
                transactionalSend([invoice.metadata], {
                    queueMetadata: { attachmentDeferrals: 1, attachmentDueAt: firstDueAt },
                })
            )
            await waitForExpect(() => expect(bucket.heldRequests).toBeGreaterThan(0))

            const before = Date.now()
            const [again, first] = await enqueue(
                transactionalSend([invoice.metadata], {
                    queueMetadata: { attachmentDeferrals: 2, attachmentDueAt: firstDueAt },
                }),
                transactionalSend([invoice.metadata], { queueScheduledAt: scheduledFirst })
            )
            const [deferredAgain, deferredFirst] = [await deferredRow(again, 3), await deferredRow(first, 1)]
            const elapsed = Date.now() - before

            expect(deferredAgain.queueMetadata).toEqual({ attachmentDeferrals: 3, attachmentDueAt: firstDueAt })
            expect(deferredAgain.scheduled.getTime() - before).toBeGreaterThanOrEqual(10_000)
            expect(deferredAgain.scheduled.getTime() - before).toBeLessThanOrEqual(20_000 + elapsed)
            expect(deferredFirst.queueMetadata).toEqual({
                attachmentDeferrals: 1,
                attachmentDueAt: scheduledFirst.toMillis(),
            })
            expect(deferredFirst.scheduled.getTime() - before).toBeGreaterThanOrEqual(5_000)
            expect(deferredFirst.scheduled.getTime() - before).toBeLessThanOrEqual(5_000 + elapsed)

            bucket.release(release)
            const admitted = await waitForExpect(async () => {
                const row = await jobRow(running)
                expect(row.status).toBe(status)
                return row
            })
            if (queueMetadata) {
                expect(admitted.queueMetadata).toEqual(queueMetadata(firstDueAt))
            }
            expect(delivered()).toEqual(inbox)
        }
    )

    it.each([
        {
            send: 'an admitted send with files',
            wait: 'its result write',
            room: 1,
            hold: (id: string) => Promise.resolve({ caught: cyclotron.hold(writeOf(completes, id)) }),
            after: 'completed',
        },
        {
            send: 'a deferred send with files',
            wait: 'its deferral write',
            room: 0,
            hold: (id: string) => Promise.resolve({ caught: cyclotron.hold(writeOf(defers, id)) }),
            after: 'available',
        },
        {
            send: 'a send with files',
            wait: 'the workflow lookup before admission',
            room: 1,
            hold: () => holdWorkflowLookup(),
            after: 'completed',
        },
    ])('renews the lease of $send while $wait waits', async ({ room, hold, after }) => {
        const send = transactionalSend([invoice.metadata])
        const { caught } = await hold(send.id)
        await enqueue(send)
        await startWorker(roomFor(room))

        const write = await caught
        const { lease } = await jobRow(send.id)
        expect(lease).not.toBeNull()
        await waitForExpect(async () => expect((await jobRow(send.id)).lease).toBeGreaterThan(lease!))
        const renewed = (await jobRow(send.id)).lease!
        await waitForExpect(async () => expect((await jobRow(send.id)).lease).toBeGreaterThan(renewed))

        await write.release()
        await waitForExpect(async () => expect((await jobRow(send.id)).status).toBe(after))
    })

    it.each([
        { failing: 'a send with files', held: 'the plain sends', failingIs: 'withFiles', heldIs: 'plain' },
        { failing: 'the plain sends', held: 'a send with files', failingIs: 'plain', heldIs: 'withFiles' },
    ] as const)(
        'counts the failed result write of $failing only once the write of $held beside it settled',
        async ({ failingIs, heldIs }) => {
            const jobs = { withFiles: transactionalSend([invoice.metadata]), plain: transactionalSend(null) }
            const failingWrite = cyclotron.hold(writeOf(completes, jobs[failingIs].id))
            const heldWrite = cyclotron.hold(writeOf(completes, jobs[heldIs].id))
            const writeFailures = (): Promise<number> =>
                metric('cdp_cyclotron_v2_result_write_failures_total', { queue: queueName })
            const backgroundsEnded = await batchPhasesEnded('background')
            await enqueue(jobs.withFiles, jobs.plain)
            await startWorker(roomFor(1))
            ;(await failingWrite).drop()
            const write = await heldWrite
            await waitForExpect(async () => expect(await batchPhasesEnded('background')).toBe(backgroundsEnded + 1))
            expect(await writeFailures()).toBe(0)

            write.release()
            await waitForExpect(async () => expect(await writeFailures()).toBe(1))
            expect(await ended(jobs[heldIs].id)).toBe('completed')
            expect((await jobRow(jobs[failingIs].id)).status).toBe('running')
        }
    )

    it('fails a plain batch only once the send with files beside it settled, and counts that send when it failed too', async () => {
        const send = transactionalSend([invoice.metadata])
        const lostRun = transactionalSend(null, { functionId: randomUUID() })
        const lostRunFails = cyclotron.hold(writeOf(fails, lostRun.id))
        const sendWrite = cyclotron.hold(writeOf(completes, send.id))
        const loopErrors = (): Promise<number> =>
            metric('cdp_cyclotron_v2_consumer_loop_errors_total', { queue: queueName })
        const failedBeside = (): Promise<number> =>
            metric('cdp_cyclotron_v2_result_write_failures_total', { queue: 'email' })
        const failedBesideBefore = await failedBeside()
        const invocationsEnded = await batchPhasesEnded('invocations')
        await enqueue(send, lostRun)
        await startWorker(roomFor(1))
        ;(await lostRunFails).drop()
        const write = await sendWrite
        await waitForExpect(async () => expect(await batchPhasesEnded('invocations')).toBe(invocationsEnded + 2))
        expect(await loopErrors()).toBe(0)

        write.drop()
        await waitForExpect(async () => expect(await loopErrors()).toBe(1))
        expect((await failedBeside()) - failedBesideBefore).toBe(1)
        expect(await metric('cdp_cyclotron_v2_result_write_failures_total', { queue: queueName })).toBe(0)
    })

    describe('with a send whose SES call never settles, not even on abort', () => {
        const callsCannotOutlast = CONSUMER_STOP_DEADLINE_MS - RESULT_WRITE_MARGIN_MS

        const stalledSes = (askedForCredentials: () => void = () => undefined): SESv2Client =>
            sesClientFor(ses, {
                credentials: () => {
                    askedForCredentials()
                    return new Promise(() => undefined)
                },
            })

        const useFakeClock = (): void => {
            jest.useFakeTimers({
                doNotFake: ['nextTick', 'setImmediate', 'clearImmediate', 'queueMicrotask', 'hrtime', 'performance'],
            })
            const timeout = jest.spyOn(AbortSignal, 'timeout').mockImplementation((ms) => {
                const controller = new AbortController()
                setTimeout(
                    () =>
                        controller.abort(new DOMException('The operation was aborted due to timeout', 'TimeoutError')),
                    ms
                )
                return controller.signal
            })
            backToRealClock = () => {
                timeout.mockRestore()
                jest.useRealTimers()
                backToRealClock = () => undefined
            }
        }

        async function onTheFakeClock<T>(check: () => Promise<T>, before: number): Promise<T> {
            for (;;) {
                try {
                    return await check()
                } catch (error) {
                    if (Date.now() + POLL_DELAY_MS >= before) {
                        throw error
                    }
                    await jest.advanceTimersByTimeAsync(POLL_DELAY_MS)
                }
            }
        }

        it('writes its result once its deadline and the wait for its call passed, before a stop that starts while it runs returns, and keeps its room taken', async () => {
            const [stuck] = await enqueue(transactionalSend([invoice.metadata]))
            const clockStarted = Date.now()
            useFakeClock()
            let callStarted = false
            const worker = await startWorker(
                roomFor(1),
                stalledSes(() => (callStarted = true))
            )
            await onTheFakeClock(async () => {
                expect((await jobRow(stuck)).status).toBe('running')
                expect(callStarted).toBe(true)
            }, clockStarted + 1_000)
            const earliestWrite = clockStarted + callsCannotOutlast

            await jest.advanceTimersByTimeAsync(earliestWrite - 2_000 - Date.now())
            const [next] = await enqueue(
                transactionalSend([invoice.metadata], { queueScheduledAt: DateTime.fromMillis(clockStarted) })
            )
            await onTheFakeClock(async () => {
                const row = await jobRow(next)
                expect({ status: row.status, deferrals: row.queueMetadata?.attachmentDeferrals }).toEqual({
                    status: 'available',
                    deferrals: 1,
                })
            }, earliestWrite)
            const beforeItIsDue = await jobRow(stuck)
            expect({ status: beforeItIsDue.status, queueMetadata: beforeItIsDue.queueMetadata }).toEqual({
                status: 'running',
                queueMetadata: undefined,
            })

            let stopReturned = false
            const stopDeadline = Date.now() + CONSUMER_STOP_DEADLINE_MS
            void worker.stop().then(() => (stopReturned = true))
            const seen: { at: number; stopReturned: boolean; status: string; retries?: number }[] = []
            await onTheFakeClock(async () => {
                const returned = stopReturned
                const row = await jobRow(stuck)
                seen.push({
                    at: Date.now(),
                    stopReturned: returned,
                    status: row.status,
                    retries: row.queueMetadata?.attachmentLoadRetries,
                })
                expect(returned).toBe(true)
            }, stopDeadline)

            expect(seen.filter((observation) => observation.stopReturned)).toEqual([
                expect.objectContaining({ status: 'available', retries: 1 }),
            ])
            const [firstWritten] = seen.filter(({ retries }) => retries !== undefined)
            expect(firstWritten.at).toBeGreaterThanOrEqual(earliestWrite)
            expect(await metric('cdp_email_attachments_sends_in_flight')).toBe(1)
            expect(delivered()).toEqual([])
        })

        it('fails a plain batch only once that send wrote its result, while its call still runs', async () => {
            const lostRun = transactionalSend(null, { functionId: randomUUID() })
            const lostRunFails = cyclotron.hold(writeOf(fails, lostRun.id))
            const loopErrors = (): Promise<number> =>
                metric('cdp_cyclotron_v2_consumer_loop_errors_total', { queue: queueName })
            const send = transactionalSend([invoice.metadata])
            await enqueue(send, lostRun)
            await startWorker(roomFor(1), stalledSes())
            ;(await lostRunFails).drop()

            await waitForExpect(async () => expect(await loopErrors()).toBe(1), callsCannotOutlast + 5_000, 50)
            expect((await jobRow(send.id)).queueMetadata?.attachmentLoadRetries).toBe(1)
            expect(await metric('cdp_email_attachments_sends_in_flight')).toBe(1)
        })
    })

    async function lockWorkflowTable(): Promise<Client> {
        const holder = new Client({ connectionString: hub.DATABASE_URL })
        await holder.connect()
        workflowTableHolders.push(holder)
        await holder.query('BEGIN')
        await holder.query('LOCK TABLE posthog_hogflow IN ACCESS EXCLUSIVE MODE')
        return holder
    }

    const workflowLookupWaits = (): Promise<void> =>
        waitForExpect(async () => {
            const { rows } = await posthogDb.query(
                `SELECT count(*)::int AS waiting FROM pg_locks WHERE relation = 'posthog_hogflow'::regclass AND NOT granted`
            )
            expect(rows[0].waiting).toBeGreaterThan(0)
        })

    async function holdWorkflowLookup(): Promise<{ caught: Promise<{ release: () => Promise<unknown> }> }> {
        const holder = await lockWorkflowTable()
        return { caught: workflowLookupWaits().then(() => ({ release: () => holder.query('COMMIT') })) }
    }

    async function reloadWorkflow(id: string): Promise<void> {
        const heard = new Promise<void>((resolve) =>
            hub.pubSub.on<{ hogFlowIds: string[] }>('reload-hog-flows', ({ hogFlowIds }) => {
                if (hogFlowIds.includes(id)) {
                    resolve()
                }
            })
        )
        await hub.pubSub.publish('reload-hog-flows', JSON.stringify({ teamId: team.id, hogFlowIds: [id] }))
        await heard
    }

    function postgresThatStopsWaitingOnLocks(): PostgresRouter {
        const withLockTimeout = (connection: string): string => {
            const url = new URL(connection)
            url.searchParams.set('options', '-c lock_timeout=100')
            return url.toString()
        }
        const router = new PostgresRouter({
            ...hub,
            DATABASE_URL: withLockTimeout(hub.DATABASE_URL),
            DATABASE_READONLY_URL: hub.DATABASE_READONLY_URL && withLockTimeout(hub.DATABASE_READONLY_URL),
        })
        routers.push(router)
        return router
    }

    const waitedTooLong = (): Partial<CyclotronJobInvocation> => ({
        queueMetadata: { attachmentDeferrals: 40, attachmentDueAt: Date.now() - LONGEST_WAIT_FOR_ROOM_MS },
    })

    it.each([
        {
            send: 'a canceled send with files on a worker that refuses files',
            room: null,
            overrides: () => ({ queueScheduledAt: DateTime.now().plus({ hours: 1 }) }),
            cancel: true,
            status: 'canceled',
            emailStatus: { status: 'failed', reason: 'canceled', sendingDomain: '' },
        },
        {
            send: 'a canceled send with files while workflow lookups fail',
            room: 1,
            overrides: () => ({ queueScheduledAt: DateTime.now().plus({ hours: 1 }) }),
            cancel: true,
            lookupsFail: true,
            status: 'canceled',
            emailStatus: { status: 'failed', reason: 'canceled', sendingDomain: '' },
        },
        {
            send: 'a send with files that waited too long on workers that refuse files',
            room: null,
            overrides: waitedTooLong,
            cancel: false,
            status: 'failed',
            emailStatus: { status: 'failed', reason: 'attachment_wait_expired', sendingDomain: '' },
        },
        {
            send: 'a send with files that waited too long for room',
            room: 0,
            overrides: waitedTooLong,
            cancel: false,
            status: 'failed',
            emailStatus: { status: 'failed', reason: 'attachment_wait_expired', sendingDomain: '' },
        },
        ...(['archived', 'draft'] as const).map((workflowStatus) => ({
            send: `a send with files of a workflow set to ${workflowStatus} while the room is taken`,
            room: 0,
            overrides: () => ({}),
            cancel: false,
            workflowStatus,
            status: 'canceled',
            emailStatus: { status: 'failed', reason: 'canceled', sendingDomain: '' },
        })),
    ] as {
        send: string
        room: number | null
        overrides: () => Partial<CyclotronJobInvocation>
        cancel: boolean
        lookupsFail?: boolean
        workflowStatus?: HogFlow['status']
        status: string
        emailStatus: EmailStatus
    }[])(
        'ends $send, instead of deferring it',
        async ({ room, overrides, cancel, lookupsFail, workflowStatus, status, emailStatus }) => {
            if (workflowStatus) {
                hogFlow = await insertHogFlow(hub.postgres, { ...emailFlow(), status: workflowStatus })
            }
            const [id] = await enqueue(transactionalSend([invoice.metadata], overrides()))
            if (lookupsFail) {
                await lockWorkflowTable()
            }
            if (cancel) {
                const manager = new CyclotronV2Manager({ pool: { dbUrl: hub.CYCLOTRON_NODE_DATABASE_URL! } })
                await manager.connect()
                await manager.cancelJobs({ teamId: team.id, functionId: hogFlow.id, jobIds: [id] })
                await manager.disconnect()
            }
            await startWorker(
                room === null ? null : roomFor(room),
                sesClientFor(ses),
                lookupsFail ? postgresThatStopsWaitingOnLocks() : hub.postgres
            )

            expect(await ended(id)).toBe(status)
            await waitForExpect(() => expect(emailStatusOf(id)).toEqual(emailStatus))
            expect(delivered()).toEqual([])
        }
    )

    it.each([
        {
            next: 'finishes the run',
            stepAfterDelay: 'exit',
            settles: async (id: string): Promise<unknown> => expect(await ended(id)).toBe('completed'),
        },
        {
            next: 'defers its next email step like a fresh send',
            stepAfterDelay: 'function_email',
            settles: (id: string): Promise<unknown> => deferredRow(id, 1),
        },
        {
            next: 'defers its next function step that sends email like a fresh send',
            stepAfterDelay: 'function',
            settles: (id: string): Promise<unknown> => deferredRow(id, 1),
        },
        {
            next: 'defers its next email step like a fresh send, when a function step sent the first email,',
            firstStep: 'function',
            stepAfterDelay: 'function_email',
            settles: (id: string): Promise<unknown> => deferredRow(id, 1),
        },
    ] as const)(
        'after an email with files went out and a delay passed, $next while the room is taken, though the first due time is long past',
        async ({ stepAfterDelay, firstStep, settles }) => {
            hogFlow = await insertEmailFlow('3s', stepAfterDelay, firstStep)
            await startWorker(roomFor(1))
            const [id] = await enqueue(transactionalSend([invoice.metadata], waitedTooLong()))
            const delayed = await waitForExpect(async () => {
                const row = await jobRow(id)
                expect({ status: row.status, inbox: delivered() }).toEqual({
                    status: 'available',
                    inbox: [['invoice.pdf']],
                })
                return row
            })
            const held = await db.query(
                "UPDATE cyclotron_jobs SET scheduled = now() + interval '1 hour' WHERE id = $1 AND status = 'available'",
                [id]
            )
            expect(held.rowCount).toBe(1)

            bucket.answer = 'hold'
            await enqueue(transactionalSend([invoice.metadata]))
            await waitForExpect(() => expect(bucket.heldRequests).toBeGreaterThan(0))
            await waitForExpect(() => expect(Date.now()).toBeGreaterThan(delayed.scheduled.getTime()), 10_000)
            await db.query('UPDATE cyclotron_jobs SET scheduled = now() WHERE id = $1', [id])

            await settles(id)
            expect(emailStatusOf(id)).toEqual({ status: 'sent', reason: '', sendingDomain: 'posthog-test.com' })
            expect(delivered()).toEqual([['invoice.pdf']])
        }
    )

    it('runs a resumed send with files on the workflow its admission checked, when that workflow changes during the lookup', async () => {
        hogFlow = await insertEmailFlow('3s')
        const changed = emailFlow('3s', 'function_email')
        await startWorker(roomFor(1))
        const [id] = await enqueue(transactionalSend([invoice.metadata]))
        await waitForExpect(async () => {
            const row = await jobRow(id)
            expect({ status: row.status, inbox: delivered() }).toEqual({
                status: 'available',
                inbox: [['invoice.pdf']],
            })
        })

        const nextDequeue = cyclotron.hold(dequeues)
        const roomTaker = transactionalSend([invoice.metadata], { functionId: (await insertEmailFlow()).id })
        await enqueue(roomTaker)
        const dequeue = await nextDequeue
        await waitForExpect(async () => {
            const { rows } = await db.query('SELECT scheduled <= now() AS due FROM cyclotron_jobs WHERE id = $1', [id])
            expect(rows[0].due).toBe(true)
        }, 10_000)
        bucket.answer = 'hold'
        const holder = await lockWorkflowTable()
        await holder.query('UPDATE posthog_hogflow SET actions = $1, edges = $2 WHERE id = $3', [
            JSON.stringify(changed.actions),
            JSON.stringify(changed.edges),
            hogFlow.id,
        ])
        dequeue.release()
        await workflowLookupWaits()
        await reloadWorkflow(hogFlow.id)
        await holder.query('COMMIT')

        await waitForExpect(async () => {
            const { status } = await jobRow(id)
            expect({ status, downloadsWaiting: bucket.heldRequests }).toEqual({
                status: 'completed',
                downloadsWaiting: 1,
            })
        })
        bucket.release()
        expect(await ended(roomTaker.id)).toBe('completed')
        expect(delivered()).toEqual([['invoice.pdf'], ['invoice.pdf']])
    })

    it.each([
        {
            send: 'a send larger than one email can carry, where it fails,',
            files: () => [{ ...invoice.metadata, sizeBytes: LARGEST_SEND_FILE_BYTES + 1 }],
            emailStatus: { status: 'failed', reason: 'message_too_large', sendingDomain: 'posthog-test.com' },
            inbox: [],
        },
        {
            send: 'a send without files as the previous version stored it, where it sends,',
            files: () => null,
            emailStatus: { status: 'sent', reason: '', sendingDomain: 'posthog-test.com' },
            inbox: [[]],
        },
    ])('runs $send in its batch on a worker that refuses files', async ({ files, emailStatus, inbox }) => {
        const [id] = await enqueue(transactionalSend(files()))
        await startWorker(null)

        expect(await ended(id)).toBe('completed')
        await waitForExpect(() => expect(emailStatusOf(id)).toEqual(emailStatus))
        expect(delivered()).toEqual(inbox)
    })

    it('holds no more than its budget under a burst, and sends every one once without failing any', async () => {
        bucket.answer = 'hold'
        const ids = await enqueue(...Array.from({ length: 6 }, () => transactionalSend([invoice.metadata])))
        await startWorker(roomFor(3))

        await waitForExpect(async () => {
            const rows = await Promise.all(ids.map(jobRow))
            expect(rows.filter((row) => row.queueMetadata?.attachmentDeferrals === 1)).toHaveLength(3)
        })
        expect(await metric('cdp_email_attachments_sends_in_flight')).toBe(3)
        expect(await metric('cdp_email_attachments_reserved_bytes')).toBe(roomFor(3).budgetBytes)

        bucket.release()
        const statuses = await Promise.all(ids.map((id) => ended(id, 20_000)))
        expect(statuses).toEqual(ids.map(() => 'completed'))
        expect(delivered()).toEqual(ids.map(() => ['invoice.pdf']))
    })
})
