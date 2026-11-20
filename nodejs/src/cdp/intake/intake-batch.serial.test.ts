import { Message } from 'node-rdkafka'
import { Pool } from 'pg'
import { MetricValueWithName, register } from 'prom-client'

import { HOG_INVOCATION_RESULTS_OUTPUT } from '~/common/outputs'
import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '~/common/outputs/types'
import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { CdpOutputs } from '../cdp-services'
import { CDP_INTAKE_DLQ_OUTPUT, CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT, EMAIL_STATUS_OUTPUT } from '../outputs/outputs'
import { CyclotronV2Manager } from '../services/cyclotron-v2/manager'
import { CdpDeadLetterService } from '../services/dead-letter/cdp-dead-letter.service'
import { createInvocationSanitizer } from '../services/job-queue/shared'
import { EmailStatusService } from '../services/messaging/email-status.service'
import {
    HogInvocationResultsService,
    HogInvocationResultsServiceOutput,
} from '../services/monitoring/hog-invocation-results.service'
import { CyclotronJobInvocation } from '../types'
import { EncryptedFields } from '../utils/encryption-utils'
import { IntakeBatchServices, SHADOW_COPY_MAX_AGE_MS, insertIntakeBatch } from './intake-batch'
import { IntakeOutput, IntakeProducer } from './intake-producer'
import { encodeIntakeMessage } from './message'
import { keyedRunId } from './run-intake'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'
const FLOW_ID = '0193a7b2-0000-7000-8000-000000000001'
const ENCRYPTION_SALT_KEYS = '00beef0000beef0000beef0000beef00'
const CDP_SEALED_STATE_KEYS = '00feed0000feed0000feed0000feed00'
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

    const kafkaMessage = (value: Buffer, timestamp?: number): Message =>
        ({
            value,
            timestamp,
            key: null,
            topic: 'cdp_intake_transactional_email',
            partition: 0,
            offset: offset++,
            size: 0,
        }) as Message

    const send = (
        overrides: {
            id?: string
            fingerprint?: string
            reply?: Record<string, unknown>
            to?: string
            shadow?: boolean
            producedAt?: number
        } = {}
    ): { id: string; message: Message } => {
        const id = overrides.id ?? new UUIDT().toString()
        const state = {
            state: {
                event: {
                    uuid: new UUIDT().toString(),
                    event: '$transactional_email',
                    timestamp: '2026-11-12T10:00:00.000Z',
                    properties: { to: overrides.to ?? 'ada@example.com' },
                },
                actionStepCount: 0,
            },
        }
        const encoded = encodeIntakeMessage({
            kind: 'transactional-email',
            fingerprint: overrides.fingerprint ?? 'fingerprint-a',
            reply: overrides.reply,
            shadow: overrides.shadow,
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
        return { id, message: kafkaMessage(encoded.message.value, overrides.producedAt) }
    }

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
            stateOpener: new EncryptedFields(CDP_SEALED_STATE_KEYS),
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

    it('carries an encrypted send from the producer to Postgres, and still writes its recipient', async () => {
        const code = 'fake-login-code-482913'
        const sealing = createInvocationSanitizer({
            CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
            CDP_SEAL_TRANSACTIONAL_EMAIL_STATE: true,
            CDP_SEALED_STATE_KEYS,
            ENCRYPTION_SALT_KEYS,
        })
        let produced: Buffer | undefined
        const topic = new IngestionOutputs({
            [CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT]: {
                ...recorder(CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT),
                produce: (message) => {
                    produced = message.value as Buffer
                    return Promise.resolve()
                },
            },
        })
        const run = {
            id: new UUIDT().toString(),
            teamId: 7,
            functionId: FLOW_ID,
            queue: 'email',
            queuePriority: 0,
            state: {
                event: {
                    uuid: new UUIDT().toString(),
                    event: '$transactional_email',
                    properties: { to: 'ada@example.com' },
                },
                variables: { code },
                actionStepCount: 0,
            },
        } as CyclotronJobInvocation

        await new IntakeProducer(topic as IngestionOutputs<IntakeOutput>, undefined, sealing.seal).produce(
            { kind: 'transactional-email', invocation: run, fingerprint: 'fingerprint-a' },
            'async'
        )
        await insertIntakeBatch([kafkaMessage(produced!)], services, OPTIONS)

        expect(produced!.toString()).not.toContain(code)
        const [job] = await storedJobs([run.id])
        expect(JSON.stringify(job.state)).not.toContain(code)
        expect(job.state.sealed).toEqual(expect.any(String))
        expect(emailStatuses()).toEqual([expect.objectContaining({ message_id: run.id, recipient: 'ada@example.com' })])
    })

    it('writes the queued status of a keyed send, dated by its trigger event', async () => {
        const id = keyedRunId(7, 'transactional-email', `key-${new UUIDT().toString()}`)

        await insertIntakeBatch([send({ id }).message], services, OPTIONS)

        expect(emailStatuses()).toEqual([
            expect.objectContaining({ message_id: id, status: 'queued', created_at: '2026-11-12 10:00:00.000000' }),
        ])
    })

    it("keeps a keyed send's reply on its claim, so a retry replays its attachment totals", async () => {
        const reply = { replayFields: { attachment_count: 2, attachment_bytes: 2048 } }
        const run = send({ reply })

        await insertIntakeBatch([run.message], services, OPTIONS)

        expect(await manager.findIdempotencyKey(run.id)).toEqual({ fingerprint: 'fingerprint-a', reply })
    })

    it('writes nothing again when Kafka redelivers a batch that committed', async () => {
        const run = send()
        await insertIntakeBatch([run.message], services, OPTIONS)
        recorded = []

        await insertIntakeBatch([run.message], services, OPTIONS)

        expect(await storedJobs([run.id])).toHaveLength(1)
        expect(recorded).toEqual([])
    })

    it.each([
        ['a fresh shadow copy', 0, 1],
        ['a shadow copy older than its claim can be trusted', SHADOW_COPY_MAX_AGE_MS + 60_000, 0],
    ])('inserts %s only while its claim still holds', async (_name, ageMs, jobs) => {
        const run = send({ shadow: true, producedAt: Date.now() - ageMs })

        await insertIntakeBatch([run.message], services, OPTIONS)

        expect(await storedJobs([run.id])).toHaveLength(jobs)
    })

    it('records how long an async run waited before its first claim, and nothing for a redelivery or a shadow copy', async () => {
        const claimDelay = async (): Promise<{ count: number; sum: number }> => {
            const values = (await register.getSingleMetric('cdp_intake_claim_delay_ms')!.get())
                .values as MetricValueWithName<string>[]
            const of = (name: string): number =>
                values.find((v) => v.metricName === name && v.labels.kind === 'transactional-email')?.value ?? 0
            return { count: of('cdp_intake_claim_delay_ms_count'), sum: of('cdp_intake_claim_delay_ms_sum') }
        }
        const before = await claimDelay()
        const run = send({ producedAt: Date.now() - 2_000 })

        await insertIntakeBatch([run.message], services, OPTIONS)
        await insertIntakeBatch([run.message], services, OPTIONS)
        const shadow = send({ shadow: true, producedAt: Date.now() - 2_000 })
        await insertIntakeBatch([shadow.message], services, OPTIONS)
        await insertIntakeBatch([shadow.message], services, OPTIONS)

        const after = await claimDelay()
        expect(after.count - before.count).toBe(1)
        expect(after.sum - before.sum).toBeGreaterThanOrEqual(2_000)
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

    it('retries a claim that hits a Postgres error, then queues the run', async () => {
        const run = send()
        let failures = 1
        const flaky: IntakeBatchServices['cyclotron'] = {
            createJobsIdempotently: (inputs) =>
                failures-- > 0
                    ? Promise.reject(new Error('Connection terminated'))
                    : manager.createJobsIdempotently(inputs),
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

    it('parks a dead letter once when the batch is retried after Postgres was down', async () => {
        const batch = [
            send().message,
            kafkaMessage(Buffer.from('not json')),
            ...Array.from({ length: 30 }, () => send().message),
        ]
        const down: IntakeBatchServices['cyclotron'] = {
            createJobsIdempotently: () => Promise.reject(new Error('Connection terminated')),
        }
        await expect(insertIntakeBatch(batch, { ...services, cyclotron: down }, OPTIONS)).rejects.toThrow()

        await insertIntakeBatch(batch, services, OPTIONS)

        expect(deadLetters()).toHaveLength(1)
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
