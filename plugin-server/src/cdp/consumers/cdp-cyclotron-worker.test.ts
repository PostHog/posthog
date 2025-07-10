import { DateTime } from 'luxon'

import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { UUIDT } from '~/utils/utils'

import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { HOG_EXAMPLES } from '../_tests/examples'
import {
    createExampleInvocation,
    createHogExecutionGlobals,
    createHogFunction,
    insertHogFunction,
} from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { CyclotronJobInvocationHogFunction, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { CdpCyclotronWorker } from './cdp-cyclotron-worker.consumer'

jest.setTimeout(1000)

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe('CdpCyclotronWorker', () => {
    let processor: CdpCyclotronWorker
    let hub: Hub
    let team: Team
    let fn: HogFunctionType
    let globals: HogFunctionInvocationGlobalsWithInputs
    let invocation: CyclotronJobInvocationHogFunction

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpCyclotronWorker(hub)

        fn = await insertHogFunction(
            hub.postgres,
            team.id,
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })
        )

        globals = {
            ...createHogExecutionGlobals({}),
            inputs: {
                url: 'https://posthog.com',
            },
        }

        invocation = createExampleInvocation(fn, globals)
        invocation.queueSource = 'postgres'
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await closeHub(hub)
    })

    describe('processInvocation', () => {
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

        it('should partially process an invocation if multiple fetches are required', async () => {
            mockFetch.mockResolvedValueOnce({
                status: 500,
                json: () => Promise.resolve({}),
                text: () => Promise.resolve(JSON.stringify({})),
                headers: {},
            } as any)

            const invocationId = invocation.id
            const results = await processor.processInvocations([invocation])
            const result = results[0]

            expect(result.finished).toBe(false)
            expect(result.error).toBe(undefined)
            expect(result.metrics).toEqual([])
            expect(result.invocation.id).toEqual(invocationId)
            expect(result.invocation.queue).toEqual('hog')
            // NOTE: Check the queue scheduled at is within the bounds of the backoff
            expect(result.invocation.queueScheduledAt?.toMillis()).toBeGreaterThan(
                DateTime.now().plus({ milliseconds: hub.CDP_FETCH_BACKOFF_BASE_MS }).toMillis()
            )
            expect(result.invocation.queueScheduledAt?.toMillis()).toBeLessThan(
                DateTime.now().plus({ milliseconds: hub.CDP_FETCH_BACKOFF_MAX_MS }).toMillis()
            )
            expect(result.invocation.queueSource).toEqual('postgres')
            expect(result.invocation.queueParameters).toMatchInlineSnapshot(`
                {
                  "body": null,
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                  "type": "fetch",
                  "url": "https://posthog.com",
                }
            `)
            expect(result.invocation.queueMetadata).toBeUndefined()
            // No logs from initial invoke
            expect(result.logs.map((x) => x.message)).toEqual([
                expect.stringContaining('HTTP fetch failed on attempt 1 with status code 500. Retrying in'),
            ])

            // Now invoke the result again
            const results2 = await processor.processInvocations([result.invocation])
            const result2 = results2[0]

            expect(result2.invocation.id).toEqual(invocationId)
            expect(result2.invocation.queueSource).toEqual('postgres')
            expect(result2.finished).toBe(true)
            expect(result2.error).toBe(undefined)
            expect(result2.metrics).toEqual([
                {
                    app_source_id: fn.id,
                    count: 1,
                    metric_kind: 'other',
                    metric_name: 'fetch',
                    team_id: team.id,
                },
            ])
            expect(result2.logs.map((x) => x.message)).toEqual([
                'Fetch response:, {"status":200,"body":{}}',
                expect.stringContaining('Function completed in'),
            ])
        })

        it('should dequeue an invocation if the hog function cannot be found', async () => {
            const dequeueInvocationsSpy = jest
                .spyOn(processor['cyclotronJobQueue'], 'dequeueInvocations')
                .mockResolvedValue(undefined)
            const invocation = createExampleInvocation(fn, globals)
            invocation.functionId = new UUIDT().toString()
            const results = await processor.processInvocations([invocation])
            expect(results).toEqual([])
            expect(dequeueInvocationsSpy).toHaveBeenCalledWith([invocation])
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

        describe('thread relief', () => {
            jest.setTimeout(10000)
            let interval: NodeJS.Timeout
            beforeEach(() => {
                jest.spyOn(Date, 'now').mockRestore()
                jest.useRealTimers()
            })

            afterEach(() => {
                clearInterval(interval)
            })

            it('should process batches in a way that does not block the main thread', async () => {
                const blockTime = 200
                let lastCheck = Date.now()
                let longestDelay = 0

                interval = setInterval(() => {
                    // Sets up an interval loop so we can see how long the longest delay between ticks is
                    longestDelay = Math.max(longestDelay, Date.now() - lastCheck)
                    lastCheck = Date.now()
                }, 1)

                const evilFunctionCode = `
                        fn fibonacci(number) {
                            print('I AM FIBONACCI. ')
                            if (number < 2) {
                                return number;
                            } else {
                                return fibonacci(number - 1) + fibonacci(number - 2);
                            }
                        }
                        print(f'fib {fibonacci(64)}');`

                const evilFunction = await insertHogFunction(
                    hub.postgres,
                    team.id,
                    createHogFunction({
                        ...HOG_FILTERS_EXAMPLES.no_filters,
                        hog: evilFunctionCode,
                        bytecode: await compileHog(evilFunctionCode),
                    })
                )

                hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS = blockTime
                hub.CDP_WATCHER_HOG_COST_TIMING_LOWER_MS = 0

                const numberToTest = 5
                const invocations = Array.from({ length: numberToTest }, () =>
                    createExampleInvocation(evilFunction, globals)
                )
                const results = await processor.processInvocations(invocations)

                const timings = results.flatMap(
                    (x) => (x.invocation.state as CyclotronJobInvocationHogFunction['state']).timings
                )

                const total = timings.reduce((acc, timing) => acc + timing.duration_ms, 0)

                // Timings is semi random so we can't test for exact values
                expect(total).toBeGreaterThan(200 * numberToTest)
                expect(total).toBeLessThan(300 * numberToTest) // the hog exec limiter isn't exact

                await new Promise((resolve) => setTimeout(resolve, 1))

                expect(longestDelay).toBeLessThan(300) // Rough upper bound of the hog exec limiter
            })
        })
    })
})
