import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { randomUUID } from 'node:crypto'
import { AddressInfo, Socket, connect, createServer } from 'node:net'
import { Pool } from 'pg'
import { register } from 'prom-client'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import {
    BucketProxy,
    SesV2Fake,
    StoredFile,
    attachmentStoreConfig,
    uploadAttachment,
} from '~/cdp/_tests/email-delivery-fakes'
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
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../types'
import { CdpCyclotronWorkerEmail, RESULT_WRITE_MARGIN_MS } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(60_000)

// The send checks the recipient's domain for mail servers in public DNS, which a test cannot rely on.
jest.mock('node:dns/promises', () => ({
    Resolver: jest.fn().mockImplementation(() => ({
        resolveMx: () => Promise.resolve([{ exchange: 'mx.example.com', priority: 10 }]),
        resolve4: () => Promise.resolve(['192.0.2.1']),
        resolve6: () => Promise.resolve([]),
    })),
}))

// The email worker sends a job only while it sits on the email queue, and other suites and runs share that
// queue in this database. So each test's jobs live on queues only that test polls, and its worker sees them
// as email jobs.
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

// Holds a query whose SQL and parameters match before Postgres sees it, so one write of a job waits while the
// job's other queries, its heartbeat included, still run. A lock inside Postgres would hold the heartbeat too,
// because both take the job's row.
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

const aMoment = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 500))

type JobRow = { status: string; scheduled: Date; lease: bigint | null; queueMetadata: Record<string, any> | undefined }
type EmailStatus = { status: string; reason: string; sendingDomain: string }

describe('CdpCyclotronWorkerEmail on Cyclotron Postgres', () => {
    let hub: Hub
    let db: Pool
    let team: Team
    let hogFlow: HogFlow
    let queueName: string
    let recipient: string
    let ses: SesV2Fake
    let bucket: BucketProxy
    let cyclotron: CyclotronProxy
    let workers: CdpCyclotronWorkerEmail[]
    let producer: EmailQueueOfOneTest
    let invoice: StoredFile

    const roomFor = (sends: number): InFlightLimits => ({
        budgetBytes: sends * estimateSend(invoice.metadata.sizeBytes).reservedBytes,
        heapLimitBytes: 64 * 1024 * 1024 * 1024,
        maxInFlight: 100,
    })

    beforeAll(async () => {
        hub = await createHub()
        db = new Pool({ connectionString: hub.CYCLOTRON_NODE_DATABASE_URL })
    })

    afterAll(async () => {
        await db.end()
        await closeHub(hub)
    })

    beforeEach(async () => {
        queueName = `email-worker-test-${randomUUID()}`
        recipient = `${randomUUID()}@example.com`
        workers = []
        team = (await createTestTeamFixture(hub.postgres)).team
        ses = await SesV2Fake.start()
        bucket = await BucketProxy.start()
        cyclotron = await CyclotronProxy.start(new URL(hub.CYCLOTRON_NODE_DATABASE_URL!))
        mockProducerObserver.resetKafkaProducer()

        const integration = await insertIntegration(hub.postgres, team.id, {
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
        const template = await insertHogFunctionTemplate(hub.postgres, {
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
        hogFlow = await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'api' } },
                        email: {
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
                        },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'email', type: 'continue' },
                        { from: 'email', to: 'exit', type: 'continue' },
                    ],
                } as any)
                .build()
        )
        invoice = await uploadAttachment(team.id, { filename: 'invoice.pdf', contentType: 'application/pdf' })
        producer = new EmailQueueOfOneTest(queueName, hub)
        await producer.startAsProducer()
    })

    afterEach(async () => {
        cyclotron.releaseAll()
        bucket.release('refuse')
        await Promise.all(workers.map((worker) => worker.stop()))
        await producer.stopProducer()
        await Promise.all([bucket.close(), ses.close(), cyclotron.close()])
        await db.query('DELETE FROM cyclotron_jobs WHERE queue_name = $1 OR queue_name LIKE $2', [
            queueName,
            `${queueName}/%`,
        ])
    })

    async function startWorker(limits: InFlightLimits | null): Promise<CdpCyclotronWorkerEmail> {
        const config = {
            ...hub,
            CYCLOTRON_NODE_DATABASE_URL: cyclotron.url,
            CDP_CYCLOTRON_BATCH_DELAY_MS: 10,
            CDP_CYCLOTRON_HEARTBEAT_INTERVAL_MS: 50,
            CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: bucket.endpoint,
            CDP_EMAIL_ATTACHMENTS_S3_PREFIX: attachmentStoreConfig.CDP_EMAIL_ATTACHMENTS_S3_PREFIX,
            EMAIL_STATUS_ENABLED: true,
        }
        const worker = new CdpCyclotronWorkerEmail(
            config,
            createCdpConsumerDeps(hub),
            new EmailQueueOfOneTest(queueName, config),
            new InFlightRegistry(limits, () => 0)
        )
        worker.emailService.sesV2Client = ses.client()
        workers.push(worker)
        await worker.start()
        return worker
    }

    // Built the way the transactional email API builds the job it queues.
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
        ses.deliveredTo(recipient).map((email) => email.attachments.map((file) => file.filename))

    // What the status API answers: the row of the message with the highest version.
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
        { send: 'an admitted send with files', write: 'result', room: 1, marker: completes, after: 'completed' },
        { send: 'a deferred send with files', write: 'deferral', room: 0, marker: defers, after: 'available' },
    ])('renews the lease of $send while its $write write waits', async ({ room, marker, after }) => {
        const send = transactionalSend([invoice.metadata])
        const held = cyclotron.hold(writeOf(marker, send.id))
        await enqueue(send)
        await startWorker(roomFor(room))

        const write = await held
        const { lease } = await jobRow(send.id)
        expect(lease).not.toBeNull()
        await waitForExpect(async () => expect((await jobRow(send.id)).lease).toBeGreaterThan(lease!))
        const renewed = (await jobRow(send.id)).lease!
        await waitForExpect(async () => expect((await jobRow(send.id)).lease).toBeGreaterThan(renewed))

        write.release()
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
            await enqueue(jobs.withFiles, jobs.plain)
            await startWorker(roomFor(1))
            ;(await failingWrite).drop()
            const write = await heldWrite
            await aMoment()
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
        await enqueue(send, lostRun)
        await startWorker(roomFor(1))
        ;(await lostRunFails).drop()
        const write = await sendWrite
        await aMoment()
        expect(await loopErrors()).toBe(0)

        write.drop()
        await waitForExpect(async () => expect(await loopErrors()).toBe(1))
        expect((await failedBeside()) - failedBesideBefore).toBe(1)
        expect(await metric('cdp_cyclotron_v2_result_write_failures_total', { queue: queueName })).toBe(0)
    })

    describe('with a send whose SES call never settles, not even on abort', () => {
        const callsCannotOutlast = CONSUMER_STOP_DEADLINE_MS - RESULT_WRITE_MARGIN_MS

        // The SDK resolves credentials before it signs a request and does not abort that step, so a credentials
        // source that never answers leaves the call running past its deadline. SES itself cannot do that: the
        // SDK aborts a request it has sent.
        const stallCredentials = (worker: CdpCyclotronWorkerEmail): void => {
            worker.emailService.sesV2Client = ses.client({ credentials: () => new Promise(() => undefined) })
        }

        it('writes its result once its deadline and the wait for its call passed, before the stop deadline less its write margin, and keeps its room taken', async () => {
            stallCredentials(await startWorker(roomFor(1)))
            const enqueuedAt = Date.now()
            const [stuck] = await enqueue(transactionalSend([invoice.metadata]))

            await waitForExpect(async () => expect((await jobRow(stuck)).status).toBe('running'))
            const retried = await waitForExpect(
                async () => {
                    const row = await jobRow(stuck)
                    expect(row.status).toBe('available')
                    return row
                },
                callsCannotOutlast + 5_000,
                50
            )
            const writtenAfter = Date.now() - enqueuedAt
            expect(retried.scheduled.getTime()).toBeGreaterThan(Date.now())
            expect(writtenAfter).toBeGreaterThanOrEqual(callsCannotOutlast)
            expect(writtenAfter).toBeLessThanOrEqual(callsCannotOutlast + 2_000)
            expect(await metric('cdp_email_attachments_sends_in_flight')).toBe(1)

            const [next] = await enqueue(transactionalSend([invoice.metadata]))
            await deferredRow(next, 1)
            expect(delivered()).toEqual([])
        })

        it('fails a plain batch only once that send wrote its result, while its call still runs', async () => {
            const lostRun = transactionalSend(null, { functionId: randomUUID() })
            const lostRunFails = cyclotron.hold(writeOf(fails, lostRun.id))
            const loopErrors = (): Promise<number> =>
                metric('cdp_cyclotron_v2_consumer_loop_errors_total', { queue: queueName })
            const send = transactionalSend([invoice.metadata])
            await enqueue(send, lostRun)
            stallCredentials(await startWorker(roomFor(1)))
            ;(await lostRunFails).drop()

            await waitForExpect(async () => expect(await loopErrors()).toBe(1), callsCannotOutlast + 5_000, 50)
            expect((await jobRow(send.id)).status).not.toBe('running')
            expect(await metric('cdp_email_attachments_sends_in_flight')).toBe(1)
        })
    })

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
    ])('ends $send, instead of deferring it', async ({ room, overrides, cancel, status, emailStatus }) => {
        const [id] = await enqueue(transactionalSend([invoice.metadata], overrides()))
        if (cancel) {
            const manager = new CyclotronV2Manager({ pool: { dbUrl: hub.CYCLOTRON_NODE_DATABASE_URL! } })
            await manager.connect()
            await manager.cancelJobs({ teamId: team.id, functionId: hogFlow.id, jobIds: [id] })
            await manager.disconnect()
        }
        await startWorker(room === null ? null : roomFor(room))

        expect(await ended(id)).toBe(status)
        await waitForExpect(() => expect(emailStatusOf(id)).toEqual(emailStatus))
        expect(delivered()).toEqual([])
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
