import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { UUIDT } from '~/utils/utils'

import { KAFKA_CDP_BACKFILL_EVENTS } from '../../config/kafka-topics'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
} from '../_tests/fixtures'
import { CyclotronJobInvocation, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpBackfillConsumer } from './cdp-backfill.consumer'

jest.mock('../../kafka/consumer')

jest.setTimeout(1000)

describe('CdpBackfillConsumer', () => {
    let processor: CdpBackfillConsumer
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs
    let invocation: CyclotronJobInvocation

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpBackfillConsumer(hub)

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

        globals = {
            ...createHogExecutionGlobals({}),
            inputs: {
                url: 'https://posthog.com',
            },
        }

        invocation = createExampleInvocation(fn, globals)
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    describe('initialization', () => {
        it('should initialize with correct topic and groupId', async () => {
            const { KafkaConsumer } = await import('../../kafka/consumer')
            const mockKafkaConsumer = KafkaConsumer as jest.MockedClass<typeof KafkaConsumer>

            await resetTestDatabase()
            const testHub = await createHub()
            new CdpBackfillConsumer(testHub)

            expect(mockKafkaConsumer).toHaveBeenCalledWith({
                groupId: 'cdp-backfill-consumer',
                topic: KAFKA_CDP_BACKFILL_EVENTS,
            })

            await closeHub(testHub)
        })

        it('should allow custom topic and groupId', async () => {
            const { KafkaConsumer } = await import('../../kafka/consumer')
            const mockKafkaConsumer = KafkaConsumer as jest.MockedClass<typeof KafkaConsumer>
            mockKafkaConsumer.mockClear()

            await resetTestDatabase()
            const testHub = await createHub()
            new CdpBackfillConsumer(testHub, 'custom-topic', 'custom-group')

            expect(mockKafkaConsumer).toHaveBeenCalledWith({
                groupId: 'custom-group',
                topic: 'custom-topic',
            })

            await closeHub(testHub)
        })
    })

    describe('parseKafkaBatch', () => {
        it('should parse kafka messages into invocations', async () => {
            const invocation1 = createExampleInvocation(fn, globals)
            const invocation2 = createExampleInvocation(fn, globals)

            const messages: Message[] = [
                {
                    value: Buffer.from(JSON.stringify(invocation1)),
                    offset: 1,
                } as any,
                {
                    value: Buffer.from(JSON.stringify(invocation2)),
                    offset: 2,
                } as any,
            ]

            const invocations = await processor['parseKafkaBatch'](messages)

            expect(invocations).toHaveLength(2)
            expect(invocations[0].id).toEqual(invocation1.id)
            expect(invocations[1].id).toEqual(invocation2.id)
        })

        it('should handle parsing errors gracefully', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('invalid json'),
                    offset: 1,
                } as any,
                {
                    value: Buffer.from(JSON.stringify(invocation)),
                    offset: 2,
                } as any,
            ]

            const invocations = await processor['parseKafkaBatch'](messages)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].id).toEqual(invocation.id)
        })

        it('should handle empty batch', async () => {
            const invocations = await processor['parseKafkaBatch']([])
            expect(invocations).toHaveLength(0)
        })
    })

    describe('processInvocations', () => {
        beforeEach(() => {
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)
        })

        it('should process a single fetch invocation fully', async () => {
            const results = await processor.processInvocations([invocation])
            const result = results[0]

            expect(result.finished).toBe(true)
            expect(result.error).toBe(undefined)
            expect(result.metrics).toEqual([
                {
                    app_source_id: fn.id,
                    count: 1,
                    metric_kind: 'other',
                    metric_name: 'fetch',
                    team_id: team.id,
                },
            ])
            expect(result.logs.map((x) => x.message)).toEqual([
                'Fetch response:, {"status":200,"body":{}}',
                expect.stringContaining('Function completed in'),
            ])
        })

        it('should route hog functions to correct executor services based on template_id', async () => {
            const segmentFn = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                    template_id: 'segment-actions-amplitude',
                })
            )

            const nativeFn = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                    template_id: 'native-webhook',
                })
            )

            const pluginFn = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                    template_id: 'plugin-posthog-intercom-plugin',
                })
            )

            const nativeExecutorSpy = jest.spyOn(processor['nativeDestinationExecutorService'], 'execute')
            const pluginExecutorSpy = jest.spyOn(processor['pluginDestinationExecutorService'], 'execute')
            const segmentExecutorSpy = jest.spyOn(processor['segmentDestinationExecutorService'], 'execute')
            const hogExecutorSpy = jest.spyOn(processor['hogExecutor'], 'executeWithAsyncFunctions')

            const invocations = [
                createExampleInvocation(nativeFn, globals),
                createExampleInvocation(pluginFn, globals),
                createExampleInvocation(segmentFn, globals),
                createExampleInvocation(fn, globals),
            ]

            await processor.processInvocations(invocations)

            expect(nativeExecutorSpy).toHaveBeenCalledTimes(1)
            expect(nativeExecutorSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    hogFunction: expect.objectContaining({ template_id: 'native-webhook' }),
                })
            )

            expect(pluginExecutorSpy).toHaveBeenCalledTimes(1)
            expect(pluginExecutorSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    hogFunction: expect.objectContaining({ template_id: 'plugin-posthog-intercom-plugin' }),
                })
            )

            expect(segmentExecutorSpy).toHaveBeenCalledTimes(1)
            expect(segmentExecutorSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    hogFunction: expect.objectContaining({ template_id: 'segment-actions-amplitude' }),
                })
            )

            expect(hogExecutorSpy).toHaveBeenCalledTimes(1)
            expect(hogExecutorSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    hogFunction: expect.objectContaining({ template_id: 'template-webhook' }),
                })
            )
        })

        it('should skip invocations if the hog function cannot be found', async () => {
            const invocation = createExampleInvocation(fn, globals)
            invocation.functionId = new UUIDT().toString()
            const results = await processor.processInvocations([invocation])
            expect(results).toEqual([])
        })

        it('should skip a loaded function if it is disabled', async () => {
            const fn2 = await insertHogFunction(
                hub.postgres,
                team.id,
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                    enabled: false,
                })
            )

            const results = await processor['loadHogFunctions']([createExampleInvocation(fn2, globals)])
            expect(results).toEqual([])
        })
    })

    describe('processBatch', () => {
        beforeEach(() => {
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)
        })

        it('should process a batch of invocations', async () => {
            const invocation1 = createExampleInvocation(fn, globals)
            const invocation2 = createExampleInvocation(fn, globals)

            const { backgroundTask, invocationResults } = await processor.processBatch([invocation1, invocation2])

            expect(invocationResults).toHaveLength(2)
            expect(invocationResults[0].finished).toBe(true)
            expect(invocationResults[1].finished).toBe(true)

            await backgroundTask
        })

        it('should handle empty batch', async () => {
            const { backgroundTask, invocationResults } = await processor.processBatch([])

            expect(invocationResults).toHaveLength(0)
            await backgroundTask
        })

        it('should queue monitoring results in background', async () => {
            const queueSpy = jest.spyOn(processor['hogFunctionMonitoringService'], 'queueInvocationResults')
            const flushSpy = jest.spyOn(processor['hogFunctionMonitoringService'], 'flush')
            const observeSpy = jest.spyOn(processor['hogWatcher'], 'observeResults')

            const { backgroundTask } = await processor.processBatch([invocation])

            await backgroundTask

            expect(queueSpy).toHaveBeenCalledTimes(1)
            expect(flushSpy).toHaveBeenCalledTimes(1)
            expect(observeSpy).toHaveBeenCalledTimes(1)
        })
    })
})
