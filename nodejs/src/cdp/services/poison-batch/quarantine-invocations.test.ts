import { mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { Message } from 'node-rdkafka'
import { register } from 'prom-client'
import { compressSync } from 'snappy'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_HOG_INVOCATION_RESULTS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper, ProducerMessage } from '~/common/kafka/producer'
import { MessageSizeTooLarge } from '~/common/utils/db/error'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'
import { createTestTeamFixture } from '~/tests/helpers/sql'

import { Hub, Team } from '../../../types'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
} from '../../_tests/fixtures'
import { createCdpCoreServices } from '../../cdp-services'
import {
    CyclotronJobInvocation,
    CyclotronJobInvocationHogFunction,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
} from '../../types'
import { CyclotronJobQueueKafka } from '../job-queue/job-queue-kafka'
import { decodeInvocationGlobals } from '../monitoring/hog-invocation-results.service'
import { InvocationQuarantine, QUARANTINED_ERROR_KIND, parseQuarantinedInvocation } from './quarantine-invocations'

describe('InvocationQuarantine', () => {
    describe('parseQuarantinedInvocation', () => {
        const state = { globals: { event: { uuid: 'event-uuid' } }, timings: [] }
        const payload = JSON.stringify({ id: 'body-id', teamId: 7, functionId: 'body-fn', state, queue: 'hog' })
        const message = (value: Buffer): Message => ({
            topic: 'cdp_cyclotron_hogdlq',
            partition: 0,
            offset: 12,
            size: value.length,
            key: Buffer.from('key-id'),
            value,
            headers: [{ teamId: Buffer.from('2') }, { functionId: Buffer.from('header-fn') }],
        })

        // A throw here crashes the dead letter worker on the message it is trying to give up on.
        it.each([
            [
                'a compressed invocation',
                compressSync(payload),
                { id: 'body-id', teamId: 7, functionId: 'body-fn', state },
            ],
            [
                'bytes that are not JSON',
                Buffer.from('not-json'),
                { id: 'key-id', teamId: 2, functionId: 'header-fn', state: null },
            ],
            [
                'JSON that is not an object',
                Buffer.from('null'),
                { id: 'key-id', teamId: 2, functionId: 'header-fn', state: null },
            ],
        ])('identifies the invocation from %s', async (_, value, expected) => {
            expect(await parseQuarantinedInvocation(message(value))).toMatchObject({ ...expected, queue: 'hogdlq' })
        })

        // ClickHouse skips a results row whose first_scheduled_at it cannot parse, and the quarantine would leave no
        // record. Without the field, the row falls back to scheduled_at, like any other writer.
        it.each([
            ['2026-11-12 08:00:00.123456', '2026-11-12 08:00:00.123456'],
            ['2026-11-12 08:00:00', '2026-11-12 08:00:00'],
            ['2026-11-12T08:00:00.000Z', undefined],
            ['2026-02-30 08:00:00.000000', undefined],
            ['garbage', undefined],
            [1731398400, undefined],
        ])('keeps state.firstScheduledAt %p only in the format ClickHouse reads', async (firstScheduledAt, kept) => {
            const value = Buffer.from(
                JSON.stringify({ id: 'id', teamId: 7, functionId: 'fn', state: { ...state, firstScheduledAt } })
            )

            const read = await parseQuarantinedInvocation(message(value))

            expect(read.state).toEqual(kept === undefined ? state : { ...state, firstScheduledAt: kept })
        })

        // A divert copies the message the hog worker produced unchanged, so the dead letter worker reads that format.
        it.each([true, false])(
            'identifies an invocation the queue produced with compression %p',
            async (compressed) => {
                const queue = new CyclotronJobQueueKafka(
                    undefined,
                    { ...defaultConfig, CDP_CYCLOTRON_COMPRESS_KAFKA_DATA: compressed },
                    1
                )
                const produce = jest.fn<Promise<void>, [ProducerMessage]>(() => Promise.resolve())
                queue['kafkaProducer'] = { produce } as unknown as KafkaProducerWrapper
                const invocation: CyclotronJobInvocation = {
                    id: 'invocation-id',
                    teamId: 7,
                    functionId: 'function-id',
                    state,
                    queue: 'hog',
                    queuePriority: 0,
                }

                await queue.queueInvocations([invocation])

                const [[produced]] = produce.mock.calls
                const read = await parseQuarantinedInvocation({
                    ...message(produced.value!),
                    key: produced.key!,
                    headers: Object.entries(produced.headers!).map(([key, value]) => ({ [key]: Buffer.from(value) })),
                })
                expect(read).toMatchObject({ id: 'invocation-id', teamId: 7, functionId: 'function-id', state })
            }
        )
    })

    describe('quarantine', () => {
        let hub: Hub
        let team: Team
        let fn: HogFunctionType
        let globals: HogFunctionInvocationGlobalsWithInputs
        let quarantine: InvocationQuarantine

        beforeEach(async () => {
            hub = await createHub({ HOG_INVOCATION_RESULTS_ENABLED: true })
            team = (await createTestTeamFixture(hub.postgres)).team
            fn = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                    template_id: 'template-webhook',
                })
            )
            globals = { ...createHogExecutionGlobals({}), inputs: { url: 'https://posthog.com' } }
            const services = createCdpCoreServices(hub, createCdpConsumerDeps(hub))
            quarantine = new InvocationQuarantine(
                'CdpCyclotronWorker',
                services.invocationResultsService.invocationResultsRowsService
            )
        })

        afterEach(async () => {
            await closeHub(hub)
        })

        const quarantinedRows = () =>
            mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_HOG_INVOCATION_RESULTS)

        // The dead letter queue reads the invocation back without its function, which is what the worker gets.
        const queued = (state: Record<string, unknown>) => {
            const { hogFunction: _unloaded, ...rest } = createExampleInvocation(fn, globals)
            return { ...rest, state } as CyclotronJobInvocationHogFunction
        }

        it.each([
            ['keeps the globals of a well formed invocation', () => queued({ globals, timings: [] }), 'uuid'],
            // The fallback keeps the dead letter worker from crashing on the row it writes to give up on the payload.
            [
                'falls back to a row without the payload when the payload breaks the row',
                () => queued({ globals, timings: 'broken' }),
                undefined,
            ],
        ])('%s', async (_, build, eventUuid) => {
            const invocation = build()

            await quarantine.quarantine([{ invocation, partition: 0, offset: 12 }])

            const rows = quarantinedRows()
            expect(rows).toEqual([
                expect.objectContaining({
                    value: expect.objectContaining({
                        invocation_id: invocation.id,
                        function_id: fn.id,
                        team_id: team.id,
                        status: 'failed',
                        error_kind: QUARANTINED_ERROR_KIND,
                    }),
                }),
            ])
            const stored = (await decodeInvocationGlobals(rows[0].value.invocation_globals as string)) as {
                event?: { uuid: string }
            }
            expect(stored.event?.uuid).toEqual(eventUuid)
        })

        let restoreProducer: (() => void) | undefined

        afterEach(() => {
            restoreProducer?.()
            restoreProducer = undefined
        })

        // Resetting the spy drops a rejection the row never used, so it cannot fail a produce in a later test.
        const breakProducer =
            (times: 'once' | 'always', error: Error = new Error('broker down')) =>
            () => {
                const spy = mockProducerObserver.produceSpy
                const produce = spy.getMockImplementation()!
                restoreProducer = () => spy.mockReset().mockImplementation(produce)
                if (times === 'once') {
                    spy.mockRejectedValueOnce(error)
                } else {
                    spy.mockRejectedValue(error)
                }
            }

        const quarantinedCount = async (outcome: string): Promise<number> =>
            (await register.getSingleMetric('cdp_invocations_quarantined_total')!.get()).values.find(
                (v) => v.labels.outcome === outcome
            )?.value ?? 0

        it.each([
            ['fails the batch when the row cannot be produced', true, breakProducer('always'), {}, 'failed', 1],
            // The retry writes the row with the globals, so a broker blip must not drop them for good.
            [
                'fails the batch instead of dropping the payload when a produce fails once',
                true,
                breakProducer('once'),
                {},
                'failed',
                1,
            ],
            // Kafka never accepts that row, so a retry would crash-loop the worker on it.
            [
                'falls back to a row without the payload when Kafka rejects the row for good',
                true,
                breakProducer('once', new MessageSizeTooLarge('too large', new Error('MSG_SIZE_TOO_LARGE'))),
                {},
                'recorded',
                2,
            ],
            // librdkafka marks other errors, such as a denied topic, not retriable, and a row without the payload
            // would fail the same way.
            [
                'fails the batch when Kafka rejects the row for a reason other than its size',
                true,
                breakProducer(
                    'always',
                    Object.assign(new Error('Broker: Topic authorization failed'), { code: 29, isRetriable: false })
                ),
                {},
                'failed',
                1,
            ],
            ['lets the batch commit when invocation results are off', false, () => {}, {}, 'unrecorded', 0],
            [
                'lets the batch commit when the invocation names no team',
                true,
                () => {},
                { teamId: NaN },
                'unrecorded',
                0,
            ],
            ['lets the batch commit when the team header was empty', true, () => {}, { teamId: 0 }, 'unrecorded', 0],
            [
                'lets the batch commit when the invocation names no function',
                true,
                () => {},
                { functionId: '' },
                'unrecorded',
                0,
            ],
            ['lets the batch commit when the invocation has no id', true, () => {}, { id: '' }, 'unrecorded', 0],
        ] as const)('%s', async (_, resultsEnabled, setUpProducer, override, outcome, producedRows) => {
            hub.HOG_INVOCATION_RESULTS_ENABLED = resultsEnabled
            setUpProducer()
            const before = await quarantinedCount(outcome)

            const quarantining = quarantine.quarantine([
                { invocation: { ...queued({ globals, timings: [] }), ...override }, partition: 0, offset: 12 },
            ])

            // A rejection keeps the dead letter queue from committing past an invocation that left no trace.
            if (outcome === 'failed') {
                await expect(quarantining).rejects.toThrow('quarantined invocation')
            } else {
                await expect(quarantining).resolves.toBeUndefined()
            }
            expect(quarantinedRows()).toHaveLength(producedRows)
            expect(await quarantinedCount(outcome)).toEqual(before + 1)
        })
    })
})
