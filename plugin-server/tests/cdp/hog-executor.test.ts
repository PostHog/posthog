import { DateTime } from 'luxon'

import { HogExecutor } from '../../src/cdp/hog-executor'
import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionInvocation, HogFunctionType } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { status } from '../../src/utils/status'
import { truth } from '../helpers/truth'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, createHogFunction, createInvocation } from './fixtures'

jest.mock('../../src/utils/status', () => ({
    status: {
        error: jest.fn(),
        info: jest.fn(),
        warn: jest.fn(),
        debug: jest.fn(),
        updatePrompt: jest.fn(),
    },
}))

const setupFetchResponse = (invocation: HogFunctionInvocation, options?: { status?: number; body?: string }): void => {
    invocation.queue = 'hog'
    invocation.queueParameters = {
        timings: [
            {
                kind: 'async_function',
                duration_ms: 100,
            },
        ],
        response: {
            status: options?.status ?? 200,
            body: options?.body ?? 'success',
        },
    }
}

describe('Hog Executor', () => {
    jest.setTimeout(1000)
    let executor: HogExecutor
    let hub: Hub

    const mockFunctionManager = {
        reloadAllHogFunctions: jest.fn(),
        getTeamHogFunctions: jest.fn(),
        getTeamHogFunction: jest.fn(),
    }

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        hub = await createHub()
        executor = new HogExecutor(hub, mockFunctionManager as any as HogFunctionManager)
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

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([hogFunction])
            mockFunctionManager.getTeamHogFunction.mockReturnValue(hogFunction)
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
                    message: "Suspending function due to async function call 'fetch'. Payload: 1872 bytes",
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
                Array [
                  "Executing function",
                  "test",
                  "{\\"nested\\":{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false}}",
                  "{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false}",
                  "substring: ***REDACTED***",
                  "{\\"input_1\\":\\"test\\",\\"secret_input_2\\":{\\"foo\\":\\"***REDACTED***\\",\\"null\\":null,\\"bool\\":false},\\"secret_input_3\\":\\"***REDACTED***\\"}",
                  "Function completed in 0ms. Sync: 0ms. Mem: 169 bytes. Ops: 28.",
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

            const body = JSON.parse((result.invocation.queueParameters as any).body!)
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
                    properties: { email: 'test@posthog.com' },
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
                Array [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1872 bytes",
                  "Resuming function",
                  "Fetch response:, {\\"status\\":200,\\"body\\":\\"success\\"}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 779 bytes. Ops: 22.",
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
                Array [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 1872 bytes",
                  "Resuming function",
                  "Fetch response:, {\\"status\\":200,\\"body\\":{\\"foo\\":\\"bar\\"}}",
                  "Function completed in 100ms. Sync: 0ms. Mem: 779 bytes. Ops: 22.",
                ]
            `)
        })
    })

    describe('filtering', () => {
        it('can filters incoming messages correctly', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

            const resultsShouldntMatch = executor.findMatchingFunctions(createHogExecutionGlobals({ groups: {} }))
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

            const resultsShouldMatch = executor.findMatchingFunctions(
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
            expect(resultsShouldMatch.matchingFunctions).toHaveLength(1)
            expect(resultsShouldMatch.nonMatchingFunctions).toHaveLength(0)
        })

        it('logs telemetry', async () => {
            hub = await createHub({ CDP_HOG_FILTERS_TELEMETRY_TEAMS: '*' })
            executor = new HogExecutor(hub, mockFunctionManager as any as HogFunctionManager)

            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.broken_filters,
            })
            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])
            const resultsShouldMatch = executor.findMatchingFunctions(
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
            expect(resultsShouldMatch.erroredFunctions).toHaveLength(1)
            expect(status.error).toHaveBeenCalledWith(
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

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])
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

            const resultsShouldntMatch = executor.findMatchingFunctions(hogGlobals1)
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

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

            const resultsShouldMatch = executor.findMatchingFunctions(hogGlobals2)
            expect(resultsShouldMatch.matchingFunctions).toHaveLength(1)
            expect(resultsShouldMatch.nonMatchingFunctions).toHaveLength(0)
        })

        it('can use elements_chain_href', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_href_filter,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])
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

            const resultsShouldntMatch = executor.findMatchingFunctions(hogGlobals1)
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

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

            const resultsShouldMatch = executor.findMatchingFunctions(hogGlobals2)
            expect(resultsShouldMatch.matchingFunctions).toHaveLength(1)
            expect(resultsShouldMatch.nonMatchingFunctions).toHaveLength(0)
        })

        it('can use elements_chain_tags and _ids', () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_tag_and_id_filter,
            })

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])
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

            const resultsShouldntMatch = executor.findMatchingFunctions(hogGlobals1)
            expect(resultsShouldntMatch.matchingFunctions).toHaveLength(0)
            expect(resultsShouldntMatch.nonMatchingFunctions).toHaveLength(1)

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

            const resultsShouldMatch = executor.findMatchingFunctions(hogGlobals2)
            expect(resultsShouldMatch.matchingFunctions).toHaveLength(1)
            expect(resultsShouldMatch.nonMatchingFunctions).toHaveLength(0)
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
            // Run the response one time simulating a successful fetch
            setupFetchResponse(result1.invocation)
            const result2 = executor.execute(result1.invocation)
            expect(result2.finished).toBe(false)
            expect(result2.error).toBe(undefined)
            expect(result2.invocation.queue).toBe('fetch')

            // This time we should see an error for hitting the loop limit
            setupFetchResponse(result2.invocation)
            const result3 = executor.execute(result1.invocation)
            expect(result3.finished).toBe(true)
            expect(result3.error).toEqual('Exceeded maximum number of async steps: 2')
            expect(result3.logs.map((log) => log.message)).toEqual([
                'Resuming function',
                'Error executing function: HogVMException: Exceeded maximum number of async steps: 2',
            ])
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

            mockFunctionManager.getTeamHogFunctions.mockReturnValue([fn])

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
                'Function exceeded maximum log entries. No more logs will be collected.',
                expect.stringContaining(
                    'Error executing function: HogVMException: Execution timed out after 0.1 seconds. Performed'
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

        it('ignores events that have already used their posthogCapture', () => {
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
