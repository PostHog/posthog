import { DateTime } from 'luxon'

import { truth } from '~/tests/helpers/truth'

import { HogExecutorService } from '../../../src/cdp/services/hog-executor.service'
import { HogFunctionInvocation, HogFunctionType } from '../../../src/cdp/types'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { logger } from '../../../src/utils/logger'
import { parseJSON } from '../../utils/json-parse'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createHogExecutionGlobals, createHogFunction, createInvocation } from '../_tests/fixtures'

const setupFetchResponse = (
    invocation: HogFunctionInvocation,
    options?: Partial<HogFunctionInvocation['queueParameters']>
): void => {
    invocation.queue = 'hog'
    invocation.queueParameters = {
        timings: [
            {
                kind: 'async_function',
                duration_ms: 100,
            },
        ],
        response: {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
        },
        body: 'success',
        ...options,
    }
}

describe('Hog Executor', () => {
    jest.setTimeout(1000)
    let executor: HogExecutorService
    let hub: Hub

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        hub = await createHub()
        executor = new HogExecutorService(hub)
    })

    describe('general event processing', () => {
        let hogFunction: HogFunctionType
        beforeEach(() => {
            hogFunction = createHogFunction({
                name: 'Test hog function',
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
        })

        it('can execute an invocation', () => {
            const invocation = createInvocation(hogFunction)

            const result = executor.execute(invocation)
            expect(result).toEqual({
                capturedPostHogEvents: [],
                invocation: {
                    id: expect.any(String),
                    teamId: 1,
                    priority: 0,
                    globals: invocation.globals,
                    hogFunction: invocation.hogFunction,
                    queue: 'fetch',
                    queueParameters: expect.any(Object),
                    timings: [
                        {
                            kind: 'hog',
                            duration_ms: 0,
                        },
                    ],
                    vmState: expect.any(Object),
                },
                finished: false,
                logs: expect.any(Array),
            })
        })

        it('can handle null input values', () => {
            hogFunction.inputs!.debug = null
            const invocation = createInvocation(hogFunction)

            const result = executor.execute(invocation)
            expect(result.finished).toBe(false)
            expect(result.error).toBeUndefined()
        })

        it('collects logs from the function', () => {
            const invocation = createInvocation(hogFunction)
            const result = executor.execute(invocation)
            expect(result.logs).toMatchObject([
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: 'Executing function',
                },
                {
                    timestamp: expect.any(DateTime),
                    level: 'debug',
                    message: "Suspending function due to async function call 'fetch'. Payload: 1951 bytes. Event: uuid",
                },
            ])
        })

        it('redacts secret values from the logs', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.input_printer,
                ...HOG_INPUTS_EXAMPLES.secret_inputs,
            })
            const invocation = createInvocation(fn)
            const result = executor.execute(invocation)

            expect(result.logs.map((x) => x.message)).toMatchInlineSnapshot(`
                [
                  "Executing function",
                  "test",
                  "{"nested":{"foo":"***REDACTED***","null":null,"bool":false}}",
                  "{"foo":"***REDACTED***","null":null,"bool":false}",
                  "substring: ***REDACTED***",
                  "{"input_1":"test","secret_input_2":{"foo":"***REDACTED***","null":null,"bool":false},"secret_input_3":"***REDACTED***"}",
                  "Function completed in 0ms. Sync: 0ms. Mem: 169 bytes. Ops: 28. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })

        it('queues up an async function call', () => {
            const invocation = createInvocation(hogFunction)
            const result = executor.execute(invocation)

            expect(result.invocation).toMatchObject({
                queue: 'fetch',
                queueParameters: {
                    url: 'https://example.com/posthog-webhook',
                    method: 'POST',
                    headers: { version: 'v=1.2.3' },
                },
            })

            const body = parseJSON((result.invocation.queueParameters as any).body!)
            expect(body).toEqual({
                event: {
                    uuid: 'uuid',
                    event: 'test',
                    elements_chain: '',
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: { $lib_version: '1.2.3' },
                    timestamp: '2024-06-07T12:00:00.000Z',
                },
                groups: {},
                nested: { foo: 'http://localhost:8000/events/1' },
                person: {
                    id: 'uuid',
                    name: 'test',
                    url: 'http://localhost:8000/persons/1',
                    properties: { email: 'test@posthog.com', first_name: 'Pumpkin' },
                },
                event_url: 'http://localhost:8000/events/1-test',
            })
        })

        it('executes the full function in a loop', () => {
            const result = executor.execute(createInvocation(hogFunction))
            const logs = result.logs.splice(0, 100)

            expect(result.finished).toBe(false)
            expect(result.invocation.queue).toBe('fetch')
            expect(result.invocation.vmState).toBeDefined()

            // Simulate what the callback does
            setupFetchResponse(result.invocation)

            const secondResult = executor.execute(result.invocation)
            logs.push(...secondResult.logs)

            expect(secondResult.finished).toBe(true)
            expect(secondResult.error).toBeUndefined()
            expect(logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1951 bytes. Event: uuid",
                  "Resuming function",
                  "Fetch response:, {"status":200,"body":"success"}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 812 bytes. Ops: 22. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })

        it('parses the responses body if a string', () => {
            const result = executor.execute(createInvocation(hogFunction))
            const logs = result.logs.splice(0, 100)
            setupFetchResponse(result.invocation, { body: JSON.stringify({ foo: 'bar' }) })

            const secondResult = executor.execute(result.invocation)
            logs.push(...secondResult.logs)

            expect(logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1951 bytes. Event: uuid",
                  "Resuming function",
                  "Fetch response:, {"status":200,"body":{"foo":"bar"}}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 812 bytes. Ops: 22. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })

        it('handles fetch errors', () => {
            const result = executor.execute(createInvocation(hogFunction))
            const logs = result.logs.splice(0, 100)
            setupFetchResponse(result.invocation, {
                body: JSON.stringify({ foo: 'bar' }),
                response: null,
                trace: [
                    {
                        kind: 'failurestatus',
                        message: '404 Not Found',
                        headers: {},
                        status: 404,
                        timestamp: DateTime.utc(),
                    },
                ],
            })

            const secondResult = executor.execute(result.invocation)
            logs.push(...secondResult.logs)

            expect(logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1951 bytes. Event: uuid",
                  "Fetch failed after 1 attempts",
                  "Fetch failure of kind failurestatus with status 404 and message 404 Not Found",
                  "Resuming function",
                  "Fetch response:, {"status":404,"body":{"foo":"bar"}}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 812 bytes. Ops: 22. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })
    })

    describe('filtering', () => {
        it('builds the correct globals object when filtering', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const inputGlobals = createHogExecutionGlobals({ groups: {} })
            expect(inputGlobals.source).toBeUndefined()
            const results = executor.buildHogFunctionInvocations([fn], inputGlobals)

            expect(results.invocations).toHaveLength(1)

            expect(results.invocations[0].globals.source).toEqual({
                name: 'Hog Function',
                url: `http://localhost:8000/projects/1/pipeline/destinations/hog-${fn.id}/configuration/`,
            })
        })

        it('can filters incoming messages correctly', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            const resultsShouldntMatch = executor.buildHogFunctionInvocations(
                [fn],
                createHogExecutionGlobals({ groups: {} })
            )
            expect(resultsShouldntMatch.invocations).toHaveLength(0)
            expect(resultsShouldntMatch.metrics).toHaveLength(1)

            const resultsShouldMatch = executor.buildHogFunctionInvocations(
                [fn],
                createHogExecutionGlobals({
                    groups: {},
                    event: {
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    } as any,
                })
            )
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })

        it('logs telemetry', async () => {
            hub = await createHub({ CDP_HOG_FILTERS_TELEMETRY_TEAMS: '*' })
            executor = new HogExecutorService(hub)

            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.broken_filters,
            })

            const resultsShouldMatch = executor.buildHogFunctionInvocations(
                [fn],
                createHogExecutionGlobals({
                    groups: {},
                    event: {
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    } as any,
                })
            )
            expect(resultsShouldMatch.metrics).toHaveLength(1)
            expect(resultsShouldMatch.logs[0].message).toMatchInlineSnapshot(
                `"Error filtering event uuid: Invalid HogQL bytecode, stack is empty, can not pop"`
            )
            expect(logger.error).toHaveBeenCalledWith(
                '🦔',
                expect.stringContaining('Error filtering function'),
                truth(
                    (obj) =>
                        'telemetry' in obj.result.state &&
                        Array.isArray(obj.result.state.telemetry) &&
                        obj.result.state.telemetry[0][3] === 'START'
                )
            )
        })

        it('can use elements_chain_texts', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_text_filter,
            })

            const elementsChain = (buttonText: string) =>
                `span.LemonButton__content:attr__class="LemonButton__content"nth-child="2"nth-of-type="2"text="${buttonText}";span.LemonButton__chrome:attr__class="LemonButton__chrome"nth-child="1"nth-of-type="1";button.LemonButton.LemonButton--has-icon.LemonButton--secondary.LemonButton--status-default:attr__class="LemonButton LemonButton--secondary LemonButton--status-default LemonButton--has-icon"attr__type="button"nth-child="1"nth-of-type="1"text="${buttonText}";div.flex.gap-4.items-center:attr__class="flex gap-4 items-center"nth-child="1"nth-of-type="1";div.flex.flex-wrap.gap-4.justify-between:attr__class="flex gap-4 justify-between flex-wrap"nth-child="3"nth-of-type="3";div.flex.flex-1.flex-col.gap-4.h-full.relative.w-full:attr__class="relative w-full flex flex-col gap-4 flex-1 h-full"nth-child="1"nth-of-type="1";div.LemonTabs__content:attr__class="LemonTabs__content"nth-child="2"nth-of-type="1";div.LemonTabs.LemonTabs--medium:attr__class="LemonTabs LemonTabs--medium"attr__style="--lemon-tabs-slider-width: 48px; --lemon-tabs-slider-offset: 0px;"nth-child="1"nth-of-type="1";div.Navigation3000__scene:attr__class="Navigation3000__scene"nth-child="2"nth-of-type="2";main:nth-child="2"nth-of-type="1";div.Navigation3000:attr__class="Navigation3000"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="3"nth-of-type="1";body.overflow-hidden:attr__class="overflow-hidden"attr__theme="light"nth-child="2"nth-of-type="1"`

            const hogGlobals1 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('Not our text'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldntMatch = executor.buildHogFunctionInvocations([fn], hogGlobals1)
            expect(resultsShouldntMatch.invocations).toHaveLength(0)
            expect(resultsShouldntMatch.metrics).toHaveLength(1)

            const hogGlobals2 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('Reload'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldMatch = executor.buildHogFunctionInvocations([fn], hogGlobals2)
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })

        it('can use elements_chain_href', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_href_filter,
            })

            const elementsChain = (link: string) =>
                `span.LemonButton__content:attr__class="LemonButton__content"attr__href="${link}"href="${link}"nth-child="2"nth-of-type="2"text="Activity";span.LemonButton__chrome:attr__class="LemonButton__chrome"nth-child="1"nth-of-type="1";a.LemonButton.LemonButton--full-width.LemonButton--has-icon.LemonButton--secondary.LemonButton--status-alt.Link.NavbarButton:attr__class="Link LemonButton LemonButton--secondary LemonButton--status-alt LemonButton--full-width LemonButton--has-icon NavbarButton"attr__data-attr="menu-item-activity"attr__href="${link}"href="${link}"nth-child="1"nth-of-type="1"text="Activity";li.w-full:attr__class="w-full"nth-child="6"nth-of-type="6";ul:nth-child="1"nth-of-type="1";div.Navbar3000__top.ScrollableShadows__inner:attr__class="ScrollableShadows__inner Navbar3000__top"nth-child="1"nth-of-type="1";div.ScrollableShadows.ScrollableShadows--vertical:attr__class="ScrollableShadows ScrollableShadows--vertical"nth-child="1"nth-of-type="1";div.Navbar3000__content:attr__class="Navbar3000__content"nth-child="1"nth-of-type="1";nav.Navbar3000:attr__class="Navbar3000"nth-child="1"nth-of-type="1";div.Navigation3000:attr__class="Navigation3000"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="3"nth-of-type="1";body.overflow-hidden:attr__class="overflow-hidden"attr__theme="light"nth-child="2"nth-of-type="1"`

            const hogGlobals1 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('/project/1/not-a-link'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldntMatch = executor.buildHogFunctionInvocations([fn], hogGlobals1)
            expect(resultsShouldntMatch.invocations).toHaveLength(0)
            expect(resultsShouldntMatch.metrics).toHaveLength(1)

            const hogGlobals2 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('/project/1/activity/explore'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldMatch = executor.buildHogFunctionInvocations([fn], hogGlobals2)
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })

        it('can use elements_chain_tags and _ids', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_tag_and_id_filter,
            })

            const elementsChain = (id: string) =>
                `a.Link.font-semibold.text-text-3000.text-xl:attr__class="Link font-semibold text-xl text-text-3000"attr__href="/project/1/dashboard/1"attr__id="${id}"attr_id="${id}"href="/project/1/dashboard/1"nth-child="1"nth-of-type="1"text="My App Dashboard";div.ProjectHomepage__dashboardheader__title:attr__class="ProjectHomepage__dashboardheader__title"nth-child="1"nth-of-type="1";div.ProjectHomepage__dashboardheader:attr__class="ProjectHomepage__dashboardheader"nth-child="2"nth-of-type="2";div.ProjectHomepage:attr__class="ProjectHomepage"nth-child="1"nth-of-type="1";div.Navigation3000__scene:attr__class="Navigation3000__scene"nth-child="2"nth-of-type="2";main:nth-child="2"nth-of-type="1";div.Navigation3000:attr__class="Navigation3000"nth-child="1"nth-of-type="1";div:attr__id="root"attr_id="root"nth-child="3"nth-of-type="1";body.overflow-hidden:attr__class="overflow-hidden"attr__theme="light"nth-child="2"nth-of-type="1"`

            const hogGlobals1 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('notfound'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldntMatch = executor.buildHogFunctionInvocations([fn], hogGlobals1)
            expect(resultsShouldntMatch.invocations).toHaveLength(0)
            expect(resultsShouldntMatch.metrics).toHaveLength(1)

            const hogGlobals2 = createHogExecutionGlobals({
                groups: {},
                event: {
                    uuid: 'uuid',
                    event: '$autocapture',
                    elements_chain: elementsChain('homelink'),
                    distinct_id: 'distinct_id',
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        $lib_version: '1.2.3',
                    },
                    timestamp: new Date().toISOString(),
                },
            })

            const resultsShouldMatch = executor.buildHogFunctionInvocations([fn], hogGlobals2)
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })
    })

    describe('mappings', () => {
        let fn: HogFunctionType
        beforeEach(() => {
            fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                mappings: [
                    {
                        // Filters for pageview or autocapture
                        ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                        inputs: {
                            url: {
                                order: 0,
                                value: 'https://example.com?q={event.event}',
                                bytecode: [
                                    '_H',
                                    1,
                                    32,
                                    'https://example.com?q=',
                                    32,
                                    'event',
                                    32,
                                    'event',
                                    1,
                                    2,
                                    2,
                                    'concat',
                                    2,
                                ],
                            },
                        },
                    },
                    {
                        // No filters so should match all events
                        ...HOG_FILTERS_EXAMPLES.no_filters,
                    },

                    {
                        // Broken filters so shouldn't match
                        ...HOG_FILTERS_EXAMPLES.broken_filters,
                    },
                ],
            })
        })

        it('can build mappings', () => {
            const pageviewGlobals = createHogExecutionGlobals({
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                } as any,
            })

            const results1 = executor.buildHogFunctionInvocations([fn], pageviewGlobals)
            expect(results1.invocations).toHaveLength(2)
            expect(results1.metrics).toHaveLength(1)
            expect(results1.logs).toHaveLength(1)
            expect(results1.logs[0].message).toMatchInlineSnapshot(
                `"Error filtering event uuid: Invalid HogQL bytecode, stack is empty, can not pop"`
            )

            const results2 = executor.buildHogFunctionInvocations(
                [fn],
                createHogExecutionGlobals({
                    event: {
                        event: 'test',
                    } as any,
                })
            )
            expect(results2.invocations).toHaveLength(1)
            expect(results2.metrics).toHaveLength(2)
            expect(results2.logs).toHaveLength(1)

            expect(results2.metrics[0].metric_name).toBe('filtered')
            expect(results2.metrics[1].metric_name).toBe('filtering_failed')
        })

        it('generates the correct inputs', () => {
            const pageviewGlobals = createHogExecutionGlobals({
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                } as any,
            })

            const result = executor.buildHogFunctionInvocations([fn], pageviewGlobals)
            // First mapping has input overrides that should be applied
            expect(result.invocations[0].globals.inputs.headers).toEqual({
                version: 'v=',
            })
            expect(result.invocations[0].globals.inputs.url).toMatchInlineSnapshot(`"https://example.com?q=$pageview"`)
            // Second mapping has no input overrides
            expect(result.invocations[1].globals.inputs.headers).toEqual({
                version: 'v=',
            })
            expect(result.invocations[1].globals.inputs.url).toMatchInlineSnapshot(
                `"https://example.com/posthog-webhook"`
            )
        })
    })

    describe('async functions', () => {
        it('prevents large looped fetch calls', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.recursive_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            // Simulate the recusive loop
            const invocation = createInvocation(fn)

            // Start the function
            const result1 = executor.execute(invocation)

            for (let i = 0; i < 4; i++) {
                // Run the response one time simulating a successful fetch
                setupFetchResponse(result1.invocation)
                const result2 = executor.execute(result1.invocation)
                expect(result2.finished).toBe(false)
                expect(result2.error).toBe(undefined)
                expect(result2.invocation.queue).toBe('fetch')
            }

            // This time we should see an error for hitting the loop limit
            setupFetchResponse(result1.invocation)
            const result3 = executor.execute(result1.invocation)
            expect(result3.finished).toBe(true)
            expect(result3.error).toEqual('Exceeded maximum number of async steps: 5')
            expect(result3.logs.map((log) => log.message)).toEqual([
                'Resuming function',
                'Error executing function on event uuid: HogVMException: Exceeded maximum number of async steps: 5',
            ])
        })

        it('adds secret headers for certain endpoints', () => {
            hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN = 'ADWORDS_TOKEN'

            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                inputs: {
                    ...HOG_INPUTS_EXAMPLES.simple_fetch.inputs,
                    url: {
                        value: 'https://googleads.googleapis.com/1234',
                        bytecode: ['_h', 32, 'https://googleads.googleapis.com/1234'],
                    },
                },
            })

            const invocation = createInvocation(fn)
            const result1 = executor.execute(invocation)
            expect((result1.invocation.queueParameters as any)?.headers).toMatchInlineSnapshot(`
                {
                  "developer-token": "ADWORDS_TOKEN",
                  "version": "v=1.2.3",
                }
            `)
            // Check it doesn't do it for redirect
            fn.inputs!.url!.bytecode = ['_h', 32, 'https://nasty.com?redirect=https://googleads.googleapis.com/1234']
            const invocation2 = createInvocation(fn)
            const result2 = executor.execute(invocation2)
            expect((result2.invocation.queueParameters as any)?.headers).toMatchInlineSnapshot(`
                {
                  "version": "v=1.2.3",
                }
            `)
        })

        it('crafts a mailjet request', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.send_email,
                ...HOG_INPUTS_EXAMPLES.email,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = executor.execute(createInvocation(fn))
            expect(result.invocation.queueParameters).toMatchInlineSnapshot(`
                {
                  "body": "{"Messages":[{"From":{"Email":"info@posthog.com","Name":""},"To":[{"Email":"test@posthog.com","Name":""}],"Subject":"Hello test@posthog.com","HTMLPart":"<html></html>"}]}",
                  "headers": {
                    "Authorization": "Basic dGVzdF9hcGlfa2V5OnRlc3Rfc2VjcmV0X2tleQ==",
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                  "return_queue": "hog",
                  "url": "https://api.mailjet.com/v3.1/send",
                }
            `)
        })
    })

    describe('slow functions', () => {
        beforeEach(() => {
            // We need to use real timers for this test as the timeout is based on real time
            jest.useRealTimers()
        })
        it('limits the execution time and exits appropriately', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.malicious_function,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = executor.execute(createInvocation(fn))
            expect(result.error).toContain('Execution timed out after 0.1 seconds. Performed ')

            expect(result.logs.map((log) => log.message)).toEqual([
                'Executing function',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'I AM FIBONACCI',
                'Function exceeded maximum log entries. No more logs will be collected. Event: uuid',
                expect.stringContaining(
                    'Error executing function on event uuid: HogVMException: Execution timed out after 0.1 seconds. Performed'
                ),
            ])
        })
    })

    describe('posthogCaptue', () => {
        it('captures events', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = executor.execute(createInvocation(fn))
            expect(result?.capturedPostHogEvents).toEqual([
                {
                    distinct_id: 'distinct_id',
                    event: 'test (copy)',
                    properties: {
                        $hog_function_execution_count: 1,
                    },
                    team_id: 1,
                    timestamp: '2024-06-07T12:00:00.000Z',
                },
            ])
        })

        it('ignores events that have already used their postHogCapture', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({
                groups: {},
                event: {
                    properties: {
                        $hog_function_execution_count: 1,
                    },
                },
            } as any)
            const result = executor.execute(createInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toEqual([])
            expect(result?.logs[1].message).toMatchInlineSnapshot(
                `"postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured."`
            )
        })
    })
})
