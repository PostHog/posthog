import { Message } from 'node-rdkafka'

import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { createOkContext } from '~/ingestion/framework/helpers'
import { dlq, drop, isDropResult, isOkResult, ok, redirect } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestTeam } from '~/tests/helpers/team'
import { EventHeaders, IncomingEvent, Team } from '~/types'

import { CommonIngestionPipelineConfig, newCommonIngestionPipeline } from './common-ingestion-pipeline'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

const DLQ_TOPIC = 'events_dlq_test'
const WARNINGS_TOPIC = 'ingestion_warnings_test'
const REDIRECT_TOPIC = 'redirect_test'
const TEST_REDIRECT_OUTPUT = 'test_redirect' as const
type TestRedirectOutput = typeof TEST_REDIRECT_OUTPUT

type MessageOnly = { message: Message }

describe('CommonIngestionPipelineBuilder', () => {
    let mockKafkaProducer: jest.Mocked<KafkaProducerWrapper>
    let mockTeamManager: jest.Mocked<TeamManager>
    let promiseScheduler: PromiseScheduler
    let config: CommonIngestionPipelineConfig<TestRedirectOutput>

    const team = createTestTeam({ id: 42, api_token: 'token-42' })

    const createMessage = (distinctId: string, eventName = 'test_event', token = team.api_token): Message => {
        const eventData = {
            event: eventName,
            distinct_id: distinctId,
            uuid: new UUIDT().toString(),
            timestamp: '2024-01-01T00:00:00Z',
            properties: {},
        }
        return {
            value: Buffer.from(JSON.stringify({ token, data: JSON.stringify(eventData), ...eventData })),
            headers: [{ token: Buffer.from(token) }, { distinct_id: Buffer.from(distinctId) }],
            topic: 'events_ingestion',
            partition: 0,
            offset: 0,
            size: 0,
            key: Buffer.from(distinctId),
        } as Message
    }

    // Drains the pipeline the way real drivers do, and enforces the builder's
    // contract along the way: side effects are handled inside the pipeline,
    // so no batch result may ever surface any to the driver.
    const runPipeline = async (
        pipeline: {
            feed: (batch: any[]) => Promise<{ ok: boolean }>
            next: () => Promise<{ elements: any[]; sideEffects?: Promise<unknown>[] } | null>
        },
        messages: Message[]
    ): Promise<{ elements: any[]; sideEffects?: Promise<unknown>[] }[]> => {
        const batch = messages.map((message) => createOkContext({ message }, { message }))
        const feedResult = await pipeline.feed(batch)
        expect(feedResult.ok).toBe(true)

        const batches = []
        let result = await pipeline.next()
        while (result !== null) {
            expect(result.sideEffects ?? []).toEqual([])
            batches.push(result)
            result = await pipeline.next()
        }
        await promiseScheduler.waitForAll()
        return batches
    }

    const okValues = (batches: { elements: any[] }[]): any[] =>
        batches
            .flatMap((batch) => batch.elements)
            .filter((element) => isOkResult(element.result))
            .map((element) => element.result.value)

    const producedTo = (topic: string): any[] =>
        mockKafkaProducer.produce.mock.calls.map((call) => call[0]).filter((arg: any) => arg.topic === topic)

    const warningsProduced = (): any[] =>
        mockKafkaProducer.queueMessages.mock.calls
            .map((call) => call[0])
            .filter((arg: any) => arg.topic === WARNINGS_TOPIC)
            .flatMap((arg: any) => arg.messages.map((m: { value: Buffer }) => parseJSON(m.value.toString())))

    function preTeamLogStep<T extends { headers: EventHeaders }>(log: string[], name: string): ProcessingStep<T, T> {
        return function preTeamLogStep(input) {
            log.push(`${name}:${input.headers.distinct_id}`)
            return Promise.resolve(ok(input))
        }
    }

    function preTeamLogChunkStep<T extends { headers: EventHeaders }>(
        log: string[],
        name: string
    ): ChunkProcessingStep<T, T> {
        return function preTeamLogChunkStep(values) {
            log.push(`${name}:[${values.map((value) => value.headers.distinct_id).join(',')}]`)
            return Promise.resolve(values.map((value) => ok(value)))
        }
    }

    function teamLogStep<T extends { event: PluginEvent }>(log: string[], name: string): ProcessingStep<T, T> {
        return function teamLogStep(input) {
            log.push(`${name}:${input.event.distinct_id}`)
            return Promise.resolve(ok(input))
        }
    }

    function teamLogChunkStep<T extends { event: PluginEvent }>(
        log: string[],
        name: string
    ): ChunkProcessingStep<T, T> {
        return function teamLogChunkStep(values) {
            log.push(`${name}:[${values.map((value) => value.event.distinct_id).join(',')}]`)
            return Promise.resolve(values.map((value) => ok(value)))
        }
    }

    beforeEach(() => {
        mockKafkaProducer = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        mockTeamManager = {
            getTeamByToken: jest
                .fn()
                .mockImplementation((token: string) => Promise.resolve(token === team.api_token ? team : null)),
        } as unknown as jest.Mocked<TeamManager>

        promiseScheduler = new PromiseScheduler()

        config = {
            teamManager: mockTeamManager,
            outputs: new IngestionOutputs({
                [DLQ_OUTPUT]: new SingleIngestionOutput(DLQ_OUTPUT, DLQ_TOPIC, mockKafkaProducer, 'test'),
                [INGESTION_WARNINGS_OUTPUT]: new SingleIngestionOutput(
                    INGESTION_WARNINGS_OUTPUT,
                    WARNINGS_TOPIC,
                    mockKafkaProducer,
                    'test'
                ),
                [TEST_REDIRECT_OUTPUT]: new SingleIngestionOutput(
                    TEST_REDIRECT_OUTPUT,
                    REDIRECT_TOPIC,
                    mockKafkaProducer,
                    'test'
                ),
            }),
            promiseScheduler,
        }
    })

    it('parses events, resolves the team, and returns results in feed order', async () => {
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(function tagStep(input) {
                return Promise.resolve(ok({ distinctId: input.event.distinct_id, teamId: input.team.id }))
            })
            .build()

        const batches = await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1')])

        expect(batches).toHaveLength(1)
        expect(okValues(batches)).toEqual([
            { distinctId: 'user-0', teamId: 42 },
            { distinctId: 'user-1', teamId: 42 },
        ])
    })

    it('runs consecutive pre-team pipe steps element by element in one sequential block', async () => {
        const log: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .pipe(preTeamLogStep(log, 'A'))
            .pipe(preTeamLogStep(log, 'B'))
            .parseMessage()
            .resolveTeam()
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1')])

        expect(log).toEqual(['A:user-0', 'B:user-0', 'A:user-1', 'B:user-1'])
    })

    it('pipeChunk closes the pre-team sequential block and receives the whole chunk at once', async () => {
        const log: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .pipe(preTeamLogStep(log, 'A'))
            .pipeChunk(preTeamLogChunkStep(log, 'C'))
            .pipe(preTeamLogStep(log, 'D'))
            .parseMessage()
            .resolveTeam()
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1'), createMessage('user-2')])

        expect(log).toEqual([
            'A:user-0',
            'A:user-1',
            'A:user-2',
            'C:[user-0,user-1,user-2]',
            'D:user-0',
            'D:user-1',
            'D:user-2',
        ])
    })

    it('coalesces and chunk-splits team-aware steps the same way as pre-team steps', async () => {
        const log: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(teamLogStep(log, 'X'))
            .pipeChunk(teamLogChunkStep(log, 'Y'))
            .pipe(teamLogStep(log, 'Z'))
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1')])

        expect(log).toEqual(['X:user-0', 'X:user-1', 'Y:[user-0,user-1]', 'Z:user-0', 'Z:user-1'])
    })

    it('drops events whose token cannot be resolved and keeps processing the rest', async () => {
        const log: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(teamLogStep(log, 'X'))
            .build()

        const batches = await runPipeline(pipeline, [
            createMessage('user-0'),
            createMessage('user-1', 'test_event', 'unknown-token'),
        ])

        expect(log).toEqual(['X:user-0'])
        const elements = batches.flatMap((batch) => batch.elements)
        expect(elements).toHaveLength(2)
        expect(isOkResult(elements[0].result)).toBe(true)
        expect(isDropResult(elements[1].result)).toBe(true)
        expect(producedTo(DLQ_TOPIC)).toHaveLength(0)
    })

    it('produces DLQ results from steps to the DLQ output', async () => {
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(function poisonStep(input) {
                if (input.event.event === 'poison') {
                    return Promise.resolve(dlq('poison_event'))
                }
                return Promise.resolve(ok(input))
            })
            .build()

        const batches = await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1', 'poison')])

        expect(producedTo(DLQ_TOPIC)).toHaveLength(1)
        expect(okValues(batches)).toHaveLength(1)
    })

    it('produces redirect results to the configured redirect output', async () => {
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly, TestRedirectOutput>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(function redirectStep(input) {
                if (input.event.event === 'redirect_me') {
                    return Promise.resolve(redirect('overflowing', TEST_REDIRECT_OUTPUT))
                }
                return Promise.resolve(ok(input))
            })
            .build()

        const batches = await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1', 'redirect_me')])

        expect(producedTo(REDIRECT_TOPIC)).toHaveLength(1)
        expect(okValues(batches)).toHaveLength(1)
    })

    it('routes warnings from pre-team and team-aware steps to the warnings output with the resolved team', async () => {
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .pipe(function preTeamWarningStep(input) {
                if (input.headers.distinct_id === 'user-0') {
                    return Promise.resolve(
                        ok(
                            input,
                            [],
                            [{ type: 'client_ingestion_warning', details: { marker: 'pre-team' }, alwaysSend: true }]
                        )
                    )
                }
                return Promise.resolve(ok(input))
            })
            .parseMessage()
            .resolveTeam()
            .pipe(function teamWarningStep(input) {
                if (input.event.distinct_id === 'user-1') {
                    return Promise.resolve(
                        ok(
                            input,
                            [],
                            [{ type: 'client_ingestion_warning', details: { marker: 'team' }, alwaysSend: true }]
                        )
                    )
                }
                if (input.event.distinct_id === 'user-2') {
                    return Promise.resolve(
                        drop(
                            'dropped_with_warning',
                            [],
                            [{ type: 'client_ingestion_warning', details: { marker: 'dropped' }, alwaysSend: true }]
                        )
                    )
                }
                return Promise.resolve(ok(input))
            })
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1'), createMessage('user-2')])

        const warnings = warningsProduced()
        expect(warnings).toHaveLength(3)
        for (const warning of warnings) {
            expect(warning.team_id).toBe(42)
            expect(warning.type).toBe('client_ingestion_warning')
        }
        const markers = warnings.map((warning) => parseJSON(warning.details).marker)
        expect(markers.sort()).toEqual(['dropped', 'pre-team', 'team'])
    })

    it('schedules step and batch hook side effects on the promise scheduler instead of returning them', async () => {
        const scheduleSpy = jest.spyOn(promiseScheduler, 'schedule')
        const beforeEffect = Promise.resolve('before')
        const stepEffect = Promise.resolve('step')
        const afterEffect = Promise.resolve('after')

        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .beforeBatch<Record<never, object>>((builder) =>
                builder.pipe(function beforeHook(input) {
                    return Promise.resolve(ok(input, [beforeEffect]))
                })
            )
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(function effectStep(input) {
                return Promise.resolve(ok(input, [stepEffect]))
            })
            .afterBatch((builder) =>
                builder.pipe(function afterHook(input) {
                    return Promise.resolve(ok(input, [afterEffect]))
                })
            )
            .build()

        // runPipeline asserts every batch result surfaces zero side effects.
        await runPipeline(pipeline, [createMessage('user-0')])

        const scheduled = scheduleSpy.mock.calls.map((call) => call[0])
        expect(scheduled).toEqual(expect.arrayContaining([beforeEffect, stepEffect, afterEffect]))
    })

    it('awaits side effects inline when awaitSideEffects is set', async () => {
        const scheduleSpy = jest.spyOn(promiseScheduler, 'schedule')
        let effectCompleted = false
        const effect = (async () => {
            await new Promise<void>((resolve) => setImmediate(resolve))
            effectCompleted = true
        })()

        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>({ ...config, awaitSideEffects: true })
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(function effectStep(input) {
                return Promise.resolve(ok(input, [effect]))
            })
            .build()

        const batch = [createMessage('user-0')].map((message) => createOkContext({ message }, { message }))
        await pipeline.feed(batch)
        let result = await pipeline.next()
        while (result !== null) {
            expect(result.sideEffects ?? []).toEqual([])
            result = await pipeline.next()
        }

        // Awaited inline: completed before the pipeline drained, nothing scheduled.
        expect(effectCompleted).toBe(true)
        expect(scheduleSpy).not.toHaveBeenCalled()
    })

    it('exposes beforeBatch context to steps and runs afterBatch once per batch with all results', async () => {
        const seenTags: string[] = []
        const afterBatchCalls: { count: number; tag: string }[] = []

        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .beforeBatch<{ batchTag: string }>((builder) =>
                builder.pipe(function attachBatchTag(input) {
                    return Promise.resolve(
                        ok({
                            elements: input.elements,
                            batchContext: { ...input.batchContext, batchTag: `tag-${input.batchContext.batchId}` },
                        })
                    )
                })
            )
            .parseHeaders()
            .pipe(function readBatchTag(input) {
                seenTags.push(input.batchTag)
                return Promise.resolve(ok(input))
            })
            .parseMessage()
            .resolveTeam()
            .afterBatch((builder) =>
                builder.pipe(function recordFlush(input) {
                    afterBatchCalls.push({ count: input.elements.length, tag: input.batchContext.batchTag })
                    return Promise.resolve(ok(input))
                })
            )
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1')])
        await runPipeline(pipeline, [createMessage('user-2')])

        expect(seenTags).toEqual(['tag-0', 'tag-0', 'tag-1'])
        expect(afterBatchCalls).toEqual([
            { count: 2, tag: 'tag-0' },
            { count: 1, tag: 'tag-1' },
        ])
    })

    it('runs groups concurrently with sequential multi-step subpipelines within each group', async () => {
        const log: string[] = []
        let releaseFirstA!: () => void
        const firstAGate = new Promise<void>((resolve) => (releaseFirstA = resolve))

        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .concurrentlyPerGroup(
                (value) => value.event.distinct_id,
                (group) =>
                    group.sequentially((element) =>
                        element
                            .pipe(async function stepOne(input) {
                                // Group a's first event waits for group b to make progress:
                                // if groups ran sequentially instead of concurrently, this
                                // would deadlock and the test would fail by timeout.
                                if (input.event.distinct_id === 'user-a' && input.event.event === 'e0') {
                                    await firstAGate
                                }
                                log.push(`one:${input.event.distinct_id}:${input.event.event}`)
                                return ok(input)
                            })
                            .pipe(function stepTwo(input) {
                                if (input.event.distinct_id === 'user-b') {
                                    releaseFirstA()
                                }
                                log.push(`two:${input.event.distinct_id}:${input.event.event}`)
                                return Promise.resolve(ok(input))
                            })
                    )
            )
            .gather()
            .pipeChunk(function afterGatherStep(values) {
                log.push(`gathered:${values.length}`)
                return Promise.resolve(values.map((value) => ok(value)))
            })
            .build()

        const batches = await runPipeline(pipeline, [
            createMessage('user-a', 'e0'),
            createMessage('user-a', 'e1'),
            createMessage('user-b', 'e2'),
            createMessage('user-b', 'e3'),
        ])

        expect(okValues(batches)).toHaveLength(4)
        // Within each group, every element runs through both steps before the next element.
        expect(log.filter((line) => line.includes(':user-a:'))).toEqual([
            'one:user-a:e0',
            'two:user-a:e0',
            'one:user-a:e1',
            'two:user-a:e1',
        ])
        expect(log.filter((line) => line.includes(':user-b:'))).toEqual([
            'one:user-b:e2',
            'two:user-b:e2',
            'one:user-b:e3',
            'two:user-b:e3',
        ])
        // Group b completed its first element while group a was still gated.
        expect(log.indexOf('two:user-b:e2')).toBeLessThan(log.indexOf('one:user-a:e0'))
        expect(log[log.length - 1]).toBe('gathered:4')
    })

    it('applies compose subpipelines with their own sequential and chunk stages', async () => {
        const log: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipe(teamLogStep(log, 'A'))
            .compose((builder) =>
                builder
                    .sequentially((element) => element.pipe(teamLogStep(log, 'X')).pipe(teamLogStep(log, 'Y')))
                    .pipeChunk(teamLogChunkStep(log, 'C'))
            )
            .pipe(teamLogStep(log, 'D'))
            .build()

        await runPipeline(pipeline, [createMessage('user-0'), createMessage('user-1')])

        expect(log).toEqual([
            'A:user-0',
            'A:user-1',
            'X:user-0',
            'Y:user-0',
            'X:user-1',
            'Y:user-1',
            'C:[user-0,user-1]',
            'D:user-0',
            'D:user-1',
        ])
    })

    it('applies the resolveTeam wrap decorator around team resolution', async () => {
        const wrapObserved: string[] = []
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam({
                wrap: (step) => async (input) => {
                    const result = await step(input)
                    wrapObserved.push(
                        isOkResult(result) ? `ok:${result.value.team.id}` : `miss:${input.headers.distinct_id}`
                    )
                    return result
                },
            })
            .build()

        const batches = await runPipeline(pipeline, [
            createMessage('user-0'),
            createMessage('user-1', 'test_event', 'unknown-token'),
        ])

        expect(wrapObserved).toEqual(['ok:42', 'miss:user-1'])
        const elements = batches.flatMap((batch) => batch.elements)
        expect(isOkResult(elements[0].result)).toBe(true)
        expect(isDropResult(elements[1].result)).toBe(true)
    })

    it('passes retry options through to chunk steps', async () => {
        let attempts = 0
        const pipeline = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config)
            .parseHeaders()
            .parseMessage()
            .resolveTeam()
            .pipeChunk(
                function flakyChunkStep(values) {
                    attempts++
                    if (attempts === 1) {
                        const transient = new Error('transient failure') as Error & { isRetriable: boolean }
                        transient.isRetriable = true
                        throw transient
                    }
                    return Promise.resolve(values.map((value) => ok(value)))
                },
                { retry: { tries: 2, sleepMs: 1, name: 'flaky_chunk' } }
            )
            .build()

        const batches = await runPipeline(pipeline, [createMessage('user-0')])

        expect(attempts).toBe(2)
        expect(okValues(batches)).toHaveLength(1)
    })

    describe('compile-time type safety', () => {
        // These assertions run at typecheck time, not at test time: each
        // misuse sits under @ts-expect-error, so if a builder refactor loosens
        // the stage constraints and a misuse starts compiling, tsc fails with
        // an unused-directive error.
        it('rejects stage misuse at compile time', () => {
            const teamDependentStep = (input: { message: Message; headers: EventHeaders; team: Team }) =>
                Promise.resolve(ok(input))
            const bodyDependentStep = (input: { message: Message; headers: EventHeaders; event: IncomingEvent }) =>
                Promise.resolve(ok(input))

            const preTeam = newCommonIngestionPipeline<MessageOnly, MessageOnly>(config).parseHeaders()

            // @ts-expect-error team-dependent steps must not typecheck before .resolveTeam()
            preTeam.pipe(teamDependentStep)

            // @ts-expect-error body-dependent steps must not typecheck before .parseMessage()
            preTeam.pipe(bodyDependentStep)

            // @ts-expect-error .resolveTeam() requires the parsed body from .parseMessage()
            preTeam.resolveTeam()

            const teamStage = preTeam.parseMessage().resolveTeam()

            // @ts-expect-error redirect outputs not declared in ROut must not typecheck
            teamStage.pipe(function undeclaredRedirectStep(_input: MessageOnly) {
                return Promise.resolve(redirect('nope', 'undeclared_output'))
            })

            const narrowed = teamStage.pipe(function narrowStep(input) {
                return Promise.resolve(ok({ teamId: input.team.id }))
            })

            // @ts-expect-error steps must accept the previous step's output type
            narrowed.pipe(teamDependentStep)

            expect(narrowed).toBeDefined()
        })
    })
})
