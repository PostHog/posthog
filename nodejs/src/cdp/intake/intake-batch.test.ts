import { Message } from 'node-rdkafka'
import { Pool } from 'pg'

import { HOG_INVOCATION_RESULTS_OUTPUT } from '~/common/outputs'
import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { CdpOutputs } from '../cdp-services'
import { CDP_INTAKE_DLQ_OUTPUT, EMAIL_STATUS_OUTPUT } from '../outputs/outputs'
import { CyclotronV2Manager } from '../services/cyclotron-v2/manager'
import { CdpDeadLetterService } from '../services/dead-letter/cdp-dead-letter.service'
import { EmailStatusService } from '../services/messaging/email-status.service'
import {
    HogInvocationResultsService,
    HogInvocationResultsServiceOutput,
} from '../services/monitoring/hog-invocation-results.service'
import { IntakeBatchServices, insertIntakeBatch } from './intake-batch'
import { encodeIntakeMessage } from './message'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const FLOW_ID = '0193a7b2-0000-7000-8000-000000000001'
const OPTIONS = { kind: 'transactional-email', claimRetry: { initialDelayMs: 0, maxElapsedMs: 0 } } as const

type Recorded = { output: string; message: IngestionOutputMessage }

describe('insertIntakeBatch', () => {
    let pool: Pool
    let manager: CyclotronV2Manager
    let recorded: Recorded[]
    let services: IntakeBatchServices
    let offset: number

    const recorder = (output: string): IngestionOutput => ({
        produce: (message) => {
            recorded.push({ output, message })
            return Promise.resolve()
        },
        queueMessages: (messages) => {
            recorded.push(...messages.map((message) => ({ output, message })))
            return Promise.resolve()
        },
        checkHealth: () => Promise.resolve(),
        checkTopicExists: () => Promise.resolve(),
    })

    const lifecycleRows = (): { invocation_id: string; status: string; error_kind: string }[] =>
        recorded
            .filter(({ output }) => output === HOG_INVOCATION_RESULTS_OUTPUT)
            .map(({ message }) => parseJSON(message.value!.toString()))

    const emailStatuses = (): { message_id: string; status: string; reason: string; recipient: string }[] =>
        recorded
            .filter(({ output }) => output === EMAIL_STATUS_OUTPUT)
            .map(({ message }) => parseJSON(message.value!.toString()))

    const deadLetters = (): Recorded['message'][] =>
        recorded.filter(({ output }) => output === CDP_INTAKE_DLQ_OUTPUT).map(({ message }) => message)

    const storedJobs = async (ids: string[]): Promise<{ id: string; state: Record<string, any> }[]> => {
        const result = await pool.query<{ id: string; state: Buffer }>(
            'SELECT id, state FROM cyclotron_jobs WHERE id = ANY($1::uuid[]) ORDER BY id',
            [ids]
        )
        return result.rows.map((row) => ({ id: row.id, state: parseJSON(row.state.toString()) }))
    }

    const kafkaMessage = (value: Buffer): Message =>
        ({
            value,
            key: null,
            topic: 'cdp_intake_transactional_email',
            partition: 0,
            offset: offset++,
            size: 0,
        }) as Message

    const send = (
        overrides: { id?: string; fingerprint?: string; sendBy?: Date; to?: string } = {}
    ): { id: string; message: Message } => {
        const id = overrides.id ?? new UUIDT().toString()
        const state = {
            state: {
                event: {
                    uuid: new UUIDT().toString(),
                    event: '$transactional_email',
                    properties: { to: overrides.to ?? 'ada@example.com' },
                },
                actionStepCount: 0,
                ...(overrides.sendBy && { sendBy: overrides.sendBy.toISOString() }),
            },
        }
        const encoded = encodeIntakeMessage({
            kind: 'transactional-email',
            fingerprint: overrides.fingerprint ?? 'fingerprint-a',
            job: {
                id,
                teamId: 7,
                functionId: FLOW_ID,
                queueName: 'email',
                priority: 0,
                scheduled: new Date(),
                state: Buffer.from(JSON.stringify(state)),
            },
        })
        if (encoded.status !== 'encoded') {
            throw new Error('expected an encoded message')
        }
        return { id, message: kafkaMessage(encoded.message.value) }
    }

    const minutesFromNow = (minutes: number): Date => new Date(Date.now() + minutes * 60_000)

    beforeAll(() => {
        pool = new Pool({ connectionString: DB_URL })
        manager = new CyclotronV2Manager({ pool: { dbUrl: DB_URL }, depthLimit: 1_000_000, depthCheckIntervalMs: 0 })
    })

    afterAll(async () => {
        await manager.disconnect()
        await pool.end()
    })

    beforeEach(() => {
        recorded = []
        offset = 0
        const outputs = new IngestionOutputs({
            [HOG_INVOCATION_RESULTS_OUTPUT]: recorder(HOG_INVOCATION_RESULTS_OUTPUT),
            [EMAIL_STATUS_OUTPUT]: recorder(EMAIL_STATUS_OUTPUT),
            [CDP_INTAKE_DLQ_OUTPUT]: recorder(CDP_INTAKE_DLQ_OUTPUT),
        })
        services = {
            cyclotron: manager,
            deadLetters: new CdpDeadLetterService(
                { CDP_DLQ_ENABLED: true, CDP_DLQ_BATCH_FAIL_RATIO: 0.1 },
                {
                    outputs: outputs as unknown as CdpOutputs,
                    output: CDP_INTAKE_DLQ_OUTPUT,
                    consumerGroup: 'cdp-intake-transactional-email-consumer',
                    parseFailuresStallBatch: true,
                }
            ),
            invocationResults: new HogInvocationResultsService(
                outputs as unknown as IngestionOutputs<HogInvocationResultsServiceOutput>,
                { HOG_INVOCATION_RESULTS_ENABLED: true }
            ),
            emailStatus: new EmailStatusService(outputs, { EMAIL_STATUS_ENABLED: true }),
        }
    })

    it('queues each run once, writes its running row and queued status, and dead-letters what can never insert', async () => {
        const first = send({ to: 'ada@example.com' })
        const second = send({ to: 'grace@example.com' })
        const invalid = kafkaMessage(Buffer.from(JSON.stringify({ v: 1, kind: 'transactional-email' })))
        const batch = Array.from({ length: 30 }, () => send().message)

        await insertIntakeBatch([first.message, second.message, first.message, invalid, ...batch], services, OPTIONS)

        const jobs = await storedJobs([first.id, second.id])
        expect(jobs.map((job) => job.id).sort()).toEqual([first.id, second.id].sort())
        expect(jobs[0].state.state.firstScheduledAt).toEqual(expect.any(String))
        expect(lifecycleRows().filter((row) => [first.id, second.id].includes(row.invocation_id))).toEqual([
            expect.objectContaining({ invocation_id: first.id, status: 'running' }),
            expect.objectContaining({ invocation_id: second.id, status: 'running' }),
        ])
        expect(emailStatuses().filter((row) => [first.id, second.id].includes(row.message_id))).toEqual([
            expect.objectContaining({ message_id: first.id, status: 'queued', recipient: 'ada@example.com' }),
            expect.objectContaining({ message_id: second.id, status: 'queued', recipient: 'grace@example.com' }),
        ])
        expect(deadLetters()).toEqual([
            expect.objectContaining({
                value: invalid.value,
                headers: expect.objectContaining({ dlq_step: 'parse', dlq_reason: 'schema_invalid' }),
            }),
        ])
    })

    it('writes nothing again when Kafka redelivers a batch that committed', async () => {
        const run = send()
        await insertIntakeBatch([run.message], services, OPTIONS)
        recorded = []

        await insertIntakeBatch([run.message], services, OPTIONS)

        expect(await storedJobs([run.id])).toHaveLength(1)
        expect(recorded).toEqual([])
    })

    it('leaves the first request untouched when its key comes back with a different request', async () => {
        const id = new UUIDT().toString()
        await insertIntakeBatch(
            [send({ id, fingerprint: 'fingerprint-a', to: 'ada@example.com' }).message],
            services,
            OPTIONS
        )
        recorded = []

        await insertIntakeBatch(
            [send({ id, fingerprint: 'fingerprint-b', to: 'eve@example.com' }).message],
            services,
            OPTIONS
        )

        const [job] = await storedJobs([id])
        expect(job.state.state.event.properties.to).toBe('ada@example.com')
        expect(recorded).toEqual([])
    })

    it('fails a send that arrives past its send-by deadline instead of queueing it', async () => {
        const late = send({ sendBy: minutesFromNow(-1) })

        await insertIntakeBatch([late.message], services, OPTIONS)

        expect(await storedJobs([late.id])).toEqual([])
        expect(lifecycleRows()).toEqual([
            expect.objectContaining({ invocation_id: late.id, status: 'failed', error_kind: 'send_deadline_exceeded' }),
        ])
        expect(emailStatuses()).toEqual([
            expect.objectContaining({ message_id: late.id, status: 'failed', reason: 'send_deadline_exceeded' }),
        ])
    })

    it('leaves a run alone when it arrives past its deadline but was claimed already', async () => {
        const id = new UUIDT().toString()
        await insertIntakeBatch([send({ id, sendBy: minutesFromNow(15) }).message], services, OPTIONS)
        recorded = []

        await insertIntakeBatch([send({ id, sendBy: minutesFromNow(-1) }).message], services, OPTIONS)

        expect(await storedJobs([id])).toHaveLength(1)
        expect(recorded).toEqual([])
    })

    it('retries a claim that hits a Postgres error, then queues the run', async () => {
        const run = send()
        let failures = 1
        const flaky: IntakeBatchServices['cyclotron'] = {
            createJobsIdempotently: (inputs) =>
                failures-- > 0
                    ? Promise.reject(new Error('Connection terminated'))
                    : manager.createJobsIdempotently(inputs),
            findLiveIdempotencyKeys: (ids) => manager.findLiveIdempotencyKeys(ids),
        }

        await insertIntakeBatch(
            [run.message],
            { ...services, cyclotron: flaky },
            {
                ...OPTIONS,
                claimRetry: { initialDelayMs: 0, maxElapsedMs: 60_000 },
            }
        )

        expect(await storedJobs([run.id])).toHaveLength(1)
    })

    it('fails the batch without writing rows or dead letters when Postgres stays down', async () => {
        const run = send()
        const invalid = kafkaMessage(Buffer.from('not json'))
        const down: IntakeBatchServices['cyclotron'] = {
            createJobsIdempotently: () => Promise.reject(new Error('Connection terminated')),
            findLiveIdempotencyKeys: () => Promise.reject(new Error('Connection terminated')),
        }

        await expect(
            insertIntakeBatch(
                [run.message, invalid, ...Array.from({ length: 30 }, () => send().message)],
                { ...services, cyclotron: down },
                OPTIONS
            )
        ).rejects.toThrow('Connection terminated')

        await services.emailStatus.flush()
        await (
            await services.invocationResults.handOffQueuedRows()
        ).produced
        expect(recorded).toEqual([])
    })

    it('fails the batch when dead letters are off, rather than skip a message that can never insert', async () => {
        const off = new CdpDeadLetterService(
            { CDP_DLQ_ENABLED: false, CDP_DLQ_BATCH_FAIL_RATIO: 0.1 },
            { outputs: {} as CdpOutputs, output: CDP_INTAKE_DLQ_OUTPUT, consumerGroup: 'test' }
        )

        await expect(
            insertIntakeBatch([kafkaMessage(Buffer.from('not json'))], { ...services, deadLetters: off }, OPTIONS)
        ).rejects.toThrow('dead letters are off')
    })

    it('writes the rows of the runs it created even when parking a dead letter fails', async () => {
        const run = send()
        const brokerDown: IntakeBatchServices['deadLetters'] = {
            recordMessageFailure: (message, failure) => services.deadLetters.recordMessageFailure(message, failure),
            produceForBatch: () => Promise.reject(new Error('broker down')),
        }

        await expect(
            insertIntakeBatch(
                [run.message, kafkaMessage(Buffer.from('not json'))],
                { ...services, deadLetters: brokerDown },
                OPTIONS
            )
        ).rejects.toThrow('broker down')

        expect(lifecycleRows()).toEqual([expect.objectContaining({ invocation_id: run.id, status: 'running' })])
        expect(emailStatuses()).toEqual([expect.objectContaining({ message_id: run.id, status: 'queued' })])
    })

    it('stalls the batch instead of dead-lettering most of it', async () => {
        const unparseable = Array.from({ length: 3 }, () => kafkaMessage(Buffer.from('not json')))

        await expect(insertIntakeBatch([...unparseable, send().message], services, OPTIONS)).rejects.toThrow(
            'Refusing to dead-letter 3 of 4 messages'
        )
        expect(deadLetters()).toEqual([])
    })
})
