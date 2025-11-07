// sort-imports-ignore
import { createServer } from 'http'
import { DateTime } from 'luxon'
import { AddressInfo } from 'net'

import { CyclotronInvocationQueueParametersFetchType } from '~/schema/cyclotron'
import { logger } from '~/utils/logger'

import { HogExecutorService } from '../../../src/cdp/services/hog-executor.service'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../../../src/cdp/types'
import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { parseJSON } from '../../utils/json-parse'
import { promisifyCallback } from '../../utils/utils'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createExampleInvocation, createHogExecutionGlobals, createHogFunction } from '../_tests/fixtures'
import { EXTEND_OBJECT_KEY } from './hog-executor.service'

// Mock before importing fetch
jest.mock('~/utils/request', () => {
    const original = jest.requireActual('~/utils/request')
    return {
        ...original,
        fetch: jest.fn().mockImplementation((url, options) => {
            return original.fetch(url, options)
        }),
    }
})

import { fetch } from '~/utils/request'

const cleanLogs = (logs: string[]): string[] => {
    // Replaces the function time with a fixed value to simplify testing
    return logs.map((log) => {
        return log.replace(/Function completed in \d+(\.\d+)?ms/, 'Function completed in REPLACEDms')
    })
}

describe('Hog Executor', () => {
    jest.setTimeout(1000)
    let executor: HogExecutorService
    let hub: Hub

    beforeEach(async () => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        hub = await createHub()
        executor = new HogExecutorService(hub)
    })

    afterEach(() => {
        // Ensure any spies (e.g., execHog, Math.random, Date.now) are restored between tests
        jest.restoreAllMocks()
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

        it('can execute an invocation', async () => {
            const invocation = createExampleInvocation(hogFunction)

            const result = await executor.execute(invocation)
            expect(result).toEqual({
                capturedPostHogEvents: [],
                invocation: {
                    state: {
                        globals: invocation.state.globals,
                        timings: [
                            {
                                kind: 'hog',
                                duration_ms: expect.any(Number),
                            },
                        ],
                        vmState: expect.any(Object),
                        attempts: 0,
                    },
                    id: expect.any(String),
                    teamId: 1,
                    hogFunction: invocation.hogFunction,
                    functionId: invocation.functionId,
                    queue: 'hog',
                    queueMetadata: undefined,
                    queueScheduledAt: undefined,
                    queueSource: undefined,
                    queueParameters: expect.any(Object),
                    queuePriority: 0,
                },
                finished: false,
                logs: expect.any(Array),
                metrics: [],
            })
        })

        it('can handle null input values', async () => {
            hogFunction.inputs!.debug = null
            const invocation = createExampleInvocation(hogFunction)

            const result = await executor.execute(invocation)
            expect(result.finished).toBe(false)
            expect(result.error).toBeUndefined()
        })

        it('can handle selecting entire object', async () => {
            const invocation = createExampleInvocation({
                ...hogFunction,
                inputs: {
                    ...hogFunction.inputs,
                    headers: {
                        value: {
                            [EXTEND_OBJECT_KEY]: '{person.properties}',
                        },
                        templating: 'hog',
                        bytecode: {
                            [EXTEND_OBJECT_KEY]: ['_H', 1, 32, 'properties', 32, 'person', 1, 2],
                        },
                        order: 3,
                    },
                },
            })

            invocation.state.globals.event.timestamp = '2024-06-07T12:00:00.000Z'

            const result = await executor.execute(invocation)
            expect(result.invocation.queueParameters).toMatchInlineSnapshot(`
                {
                  "body": "{"event":{"uuid":"uuid","event":"test","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$lib_version":"1.2.3"},"timestamp":"2024-06-07T12:00:00.000Z"},"groups":{},"nested":{"foo":"http://localhost:8000/events/1"},"person":{"id":"uuid","name":"test","url":"http://localhost:8000/persons/1","properties":{"email":"test@posthog.com","first_name":"Pumpkin"}},"event_url":"http://localhost:8000/events/1-test"}",
                  "headers": {
                    "email": "test@posthog.com",
                    "first_name": "Pumpkin",
                  },
                  "method": "POST",
                  "type": "fetch",
                  "url": "https://example.com/posthog-webhook",
                }
            `)
            expect(result.finished).toBe(false)
            expect(result.error).toBeUndefined()
        })

        it('can handle selecting entire object with overrides', async () => {
            const invocation = createExampleInvocation({
                ...hogFunction,
                inputs: {
                    ...hogFunction.inputs,
                    headers: {
                        value: {
                            [EXTEND_OBJECT_KEY]: '{person.properties}',
                            email: 'email-is-hidden',
                        },
                        templating: 'hog',
                        bytecode: {
                            [EXTEND_OBJECT_KEY]: ['_H', 1, 32, 'properties', 32, 'person', 1, 2],
                            email: ['_H', 1, 32, 'email-is-hidden'],
                        },
                        order: 3,
                    },
                },
            })

            invocation.state.globals.event.timestamp = '2024-06-07T12:00:00.000Z'

            const result = await executor.execute(invocation)
            expect(result.invocation.queueParameters).toMatchInlineSnapshot(`
                {
                  "body": "{"event":{"uuid":"uuid","event":"test","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$lib_version":"1.2.3"},"timestamp":"2024-06-07T12:00:00.000Z"},"groups":{},"nested":{"foo":"http://localhost:8000/events/1"},"person":{"id":"uuid","name":"test","url":"http://localhost:8000/persons/1","properties":{"email":"test@posthog.com","first_name":"Pumpkin"}},"event_url":"http://localhost:8000/events/1-test"}",
                  "headers": {
                    "email": "email-is-hidden",
                    "first_name": "Pumpkin",
                  },
                  "method": "POST",
                  "type": "fetch",
                  "url": "https://example.com/posthog-webhook",
                }
            `)
            expect(result.finished).toBe(false)
            expect(result.error).toBeUndefined()
        })

        it('collects and redacts secret values from the logs', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.input_printer,
                ...HOG_INPUTS_EXAMPLES.secret_inputs,
            })
            const invocation = createExampleInvocation(fn)
            const result = await executor.execute(invocation)

            expect(cleanLogs(result.logs.map((x) => x.message))).toMatchInlineSnapshot(`
                [
                  "test",
                  "{"nested":{"foo":"***REDACTED***","null":null,"bool":false}}",
                  "{"foo":"***REDACTED***","null":null,"bool":false}",
                  "substring: ***REDACTED***",
                  "{"input_1":"test","secret_input_2":{"foo":"***REDACTED***","null":null,"bool":false},"secret_input_3":"***REDACTED***"}",
                  "Function completed in REPLACEDms. Sync: 0ms. Mem: 0.17kb. Ops: 28. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })

        it('queues up an async function call', async () => {
            const invocation = createExampleInvocation(hogFunction)
            invocation.state.globals.event.timestamp = '2024-06-07T12:00:00.000Z'
            const result = await executor.execute(invocation)

            expect(result.invocation).toMatchObject({
                queue: 'hog',
                queueParameters: {
                    type: 'fetch',
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

        it('merges previousResult into execute() result', async () => {
            const invocation = createExampleInvocation(hogFunction)

            const previousResult = {
                finished: false,
                logs: [{ level: 'info', timestamp: DateTime.utc(), message: 'Prev log' }],
                metrics: [
                    {
                        team_id: 1,
                        app_source_id: invocation.functionId,
                        metric_kind: 'other',
                        metric_name: 'prev_metric',
                        count: 1,
                    },
                ],
                capturedPostHogEvents: [
                    {
                        team_id: 1,
                        timestamp: DateTime.utc().toISO(),
                        distinct_id: 'did',
                        event: 'prev_event',
                        properties: {},
                    },
                ],
                execResult: { foo: 'bar' },
            } as any

            const result = await executor.execute(invocation, undefined, previousResult)

            // No new logs are produced before async fetch, so previous logs/metrics/events should persist
            expect(result.logs.map((l) => l.message)).toEqual(['Prev log'])
            expect(result.metrics).toEqual(previousResult.metrics)
            expect(result.capturedPostHogEvents).toEqual(previousResult.capturedPostHogEvents)
            expect(result.execResult).toEqual({ foo: 'bar' })
        })
    })

    describe('filtering', () => {
        it('builds the correct globals object when filtering', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const inputGlobals = createHogExecutionGlobals({ groups: {} })
            expect(inputGlobals.source).toBeUndefined()
            const results = await executor.buildHogFunctionInvocations([fn], inputGlobals)

            expect(results.invocations).toHaveLength(1)

            expect(results.invocations[0].state.globals.source).toEqual({
                name: 'Hog Function',
                url: `http://localhost:8000/projects/1/pipeline/destinations/hog-${fn.id}/configuration/`,
            })
        })

        it('can filters incoming messages correctly', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            const resultsShouldntMatch = await executor.buildHogFunctionInvocations(
                [fn],
                createHogExecutionGlobals({ groups: {} })
            )
            expect(resultsShouldntMatch.invocations).toHaveLength(0)
            expect(resultsShouldntMatch.metrics).toHaveLength(1)

            const resultsShouldMatch = await executor.buildHogFunctionInvocations(
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

        it('can use elements_chain_texts', async () => {
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

            const resultsShouldntMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals1)
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

            const resultsShouldMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals2)
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })

        it('can use elements_chain_href', async () => {
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

            const resultsShouldntMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals1)
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

            const resultsShouldMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals2)
            expect(resultsShouldMatch.invocations).toHaveLength(1)
            expect(resultsShouldMatch.metrics).toHaveLength(0)
        })

        it('can use elements_chain_tags and _ids', async () => {
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

            const resultsShouldntMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals1)
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

            const resultsShouldMatch = await executor.buildHogFunctionInvocations([fn], hogGlobals2)
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

        it('can build mappings', async () => {
            const pageviewGlobals = createHogExecutionGlobals({
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                } as any,
            })

            const results1 = await executor.buildHogFunctionInvocations([fn], pageviewGlobals)
            expect(results1.invocations).toHaveLength(2)
            expect(results1.metrics).toHaveLength(1)
            expect(results1.logs).toHaveLength(1)
            expect(results1.logs[0].message).toMatchInlineSnapshot(
                `"Error filtering event uuid: Invalid HogQL bytecode, stack is empty, can not pop"`
            )

            const results2 = await executor.buildHogFunctionInvocations(
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

        it('generates the correct inputs', async () => {
            const pageviewGlobals = createHogExecutionGlobals({
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                } as any,
            })

            const result = await executor.buildHogFunctionInvocations([fn], pageviewGlobals)
            // First mapping has input overrides that should be applied
            expect(result.invocations[0].state.globals.inputs.headers).toEqual({
                version: 'v=',
            })
            expect(result.invocations[0].state.globals.inputs.url).toMatchInlineSnapshot(
                `"https://example.com?q=$pageview"`
            )
            // Second mapping has no input overrides
            expect(result.invocations[1].state.globals.inputs.headers).toEqual({
                version: 'v=',
            })
            expect(result.invocations[1].state.globals.inputs.url).toMatchInlineSnapshot(
                `"https://example.com/posthog-webhook"`
            )
        })
    })

    describe('slow functions', () => {
        it('limits the execution time and exits appropriately', async () => {
            jest.spyOn(Date, 'now').mockRestore()

            const fn = createHogFunction({
                ...HOG_EXAMPLES.malicious_function,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = await executor.execute(createExampleInvocation(fn))
            expect(result.error).toContain('Execution timed out after 0.55 seconds. Performed ')

            expect(result.logs.map((log) => log.message)).toEqual([
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
                    'Error executing function on event uuid: HogVMException: Execution timed out after 0.55 seconds. Performed'
                ),
            ])
        })
    })

    describe('result handling', () => {
        it('does not set execResult when VM returns a falsy result', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const hogExecModule = require('../utils/hog-exec')
            jest.spyOn(hogExecModule, 'execHog').mockResolvedValue({
                execResult: {
                    finished: true,
                    result: null, // falsy value
                    state: { syncDuration: 0, maxMemUsed: 1024 * 0.17, ops: 28, stack: [] },
                },
                error: undefined,
                durationMs: 1,
                waitedForThreadRelief: false,
            })

            const res = await executor.execute(createExampleInvocation(fn))
            expect(res.finished).toBe(true)
            expect(res.execResult).toBeUndefined()
            expect(cleanLogs(res.logs.map((x) => x.message))).toEqual([
                "Function completed in REPLACEDms. Sync: 0ms. Mem: 0.17kb. Ops: 28. Event: 'http://localhost:8000/events/1'",
            ])
        })
    })

    describe('posthogCaptue', () => {
        it('captures events', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const result = await executor.execute(createExampleInvocation(fn))
            expect(result?.capturedPostHogEvents).toMatchInlineSnapshot(`
                [
                  {
                    "distinct_id": "distinct_id",
                    "event": "test (copy)",
                    "properties": {
                      "$hog_function_execution_count": 1,
                    },
                    "team_id": 1,
                    "timestamp": "2025-01-01T00:00:00.000Z",
                  },
                ]
            `)
        })

        it('ignores events that have already used their postHogCapture', async () => {
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
            const result = await executor.execute(createExampleInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toEqual([])
            expect(cleanLogs(result?.logs.map((log) => log.message) ?? [])).toMatchInlineSnapshot(`
                [
                  "postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured.",
                  "Function completed in REPLACEDms. Sync: 0ms. Mem: 0.1kb. Ops: 15. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })
    })

    describe('executeFetch', () => {
        jest.setTimeout(10000)
        let server: any
        let baseUrl: string
        const mockRequest = jest.fn()
        let timeoutHandle: NodeJS.Timeout | undefined
        let hogFunction: HogFunctionType

        beforeAll(async () => {
            server = createServer((req, res) => {
                mockRequest(req, res)
            })

            await promisifyCallback<void>((cb) => {
                server.listen(0, () => {
                    logger.info('Server listening')
                    cb(null, server)
                })
            })
            const address = server.address() as AddressInfo
            baseUrl = `http://localhost:${address.port}`

            hogFunction = createHogFunction({
                name: 'Test hog function',
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })
        })

        afterEach(() => {
            clearTimeout(timeoutHandle)
        })

        afterAll(async () => {
            logger.info('Closing server')
            await promisifyCallback<void>((cb) => {
                logger.info('Closed server')
                server.close(cb)
            })
        })

        beforeEach(() => {
            jest.spyOn(Math, 'random').mockReturnValue(0.5)

            mockRequest.mockImplementation((req, res) => {
                res.writeHead(200, { 'Content-Type': 'text/plain' })
                res.end('Hello, world!')
            })
        })

        const createFetchInvocation = async (
            params: Omit<CyclotronInvocationQueueParametersFetchType, 'type'>
        ): Promise<CyclotronJobInvocationHogFunction> => {
            const invocation = createExampleInvocation(hogFunction)

            // Execute just to have an expecting stack
            const res = await executor.execute(invocation)
            expect(res.invocation.queueParameters?.type).toBe('fetch')

            // Simulate what the callback does
            invocation.queue = 'hog'
            invocation.queueParameters = {
                type: 'fetch',
                ...params,
            } as any
            return invocation
        }

        it('completes successful fetch', async () => {
            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
                body: 'test body',
            })

            const result = await executor.executeFetch(invocation)

            expect(mockRequest).toHaveBeenCalledWith(
                expect.objectContaining({
                    method: 'GET',
                    url: '/test',
                }),
                expect.any(Object)
            )

            // General check for clearance of the invocation
            expect(result.finished).toBe(false)
            expect(result.error).toBeUndefined()
            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueParameters).toBeUndefined()
            expect(result.invocation.queueMetadata).toBeUndefined()
            expect(result.invocation.queuePriority).toEqual(0)
            expect(result.invocation.queueScheduledAt).toBeUndefined()

            // State checks
            expect(result.invocation.state.attempts).toBe(0)
            expect(result.invocation.state.timings.slice(-1)).toEqual([
                expect.objectContaining({
                    kind: 'async_function',
                    duration_ms: expect.any(Number),
                }),
            ])

            expect(result.invocation.state.vmState!.stack.slice(-1)).toEqual([
                {
                    status: 200,
                    body: 'Hello, world!',
                },
            ])

            // Now also exposed on the execResult for callers of execute()
            expect(result.execResult).toEqual({ status: 200, body: 'Hello, world!' })
        })

        it('handles failure status and retries', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                res.writeHead(500, { 'Content-Type': 'text/plain' })
                res.end('test server error body')
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
                max_tries: 2,
            })

            const vmStateStackLength = invocation.state.vmState!.stack.length

            let result = await executor.executeFetch(invocation)

            // Should be scheduled for retry
            expect(result.invocation.state.attempts).toBe(1)
            expect(result.logs.map((log) => log.message)).toEqual([
                'HTTP fetch failed on attempt 1 with status code 500. Retrying in 1500ms.',
            ])
            expect(result.invocation.queuePriority).toBe(1) // Priority decreased
            expect(result.invocation.queueScheduledAt?.toISO()).toMatchInlineSnapshot(`"2025-01-01T00:00:01.500Z"`)
            expect(result.invocation.state.vmState!.stack.length).toBe(vmStateStackLength)

            // Execute the retry
            result = await executor.executeFetch(result.invocation)
            expect(result.invocation.state.attempts).toBe(2)
            expect(result.logs.map((log) => log.message)).toEqual([
                'HTTP fetch failed on attempt 2 with status code 500. Retrying in 2500ms.',
            ])
            expect(result.invocation.queuePriority).toBe(2) // Priority decreased
            expect(result.invocation.queueScheduledAt?.toISO()).toMatchInlineSnapshot(`"2025-01-01T00:00:02.500Z"`)
            expect(result.invocation.state.vmState!.stack.length).toBe(vmStateStackLength)
            // Execute the final retry
            result = await executor.executeFetch(result.invocation)
            expect(result.logs.map((log) => log.message)).toEqual([
                'HTTP fetch failed on attempt 3 with status code 500. Retrying in 3500ms.',
            ])
            // All values reset due to no longer retrying
            expect(result.invocation.state.attempts).toBe(0)
            expect(result.invocation.queuePriority).toBe(0) // Priority reset as we are no longer retrying
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            // Should now be complete with failure response
            expect(result.invocation.state.vmState!.stack.length).toBe(vmStateStackLength + 1)
            const response = result.invocation.state.vmState!.stack.slice(-1)[0]
            expect(response).toMatchInlineSnapshot(`
                {
                  "body": "test server error body",
                  "status": 500,
                }
            `)
            expect(result.invocation.queue).toBe('hog')
        })

        it('handles request errors', async () => {
            const invocation = await createFetchInvocation({
                url: 'http://non-existent-host-name',
                method: 'GET',
            })

            const result = await executor.executeFetch(invocation)

            // Should be scheduled for retry
            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueScheduledAt).toMatchInlineSnapshot(`"2025-01-01T00:00:01.500Z"`)
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "HTTP fetch failed on attempt 1 with status code (none). Error: Invalid hostname. Retrying in 1500ms.",
                ]
            `)
        })

        it('handles security errors', async () => {
            process.env.NODE_ENV = 'production' // Make sure the security features are enabled

            const invocation = await createFetchInvocation({
                url: 'http://localhost',
                method: 'GET',
            })

            const result = await executor.executeFetch(invocation)

            // Should be scheduled for retry
            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueScheduledAt).toBeUndefined()
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "HTTP fetch failed on attempt 1 with status code (none). Error: Hostname is not allowed.",
                ]
            `)

            process.env.NODE_ENV = 'test'
        })

        it('handles timeouts', async () => {
            mockRequest.mockImplementation((_req: any, res: any) => {
                // Never send response
                clearTimeout(timeoutHandle)
                timeoutHandle = setTimeout(() => res.end(), 10000)
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
            })

            // Set a very short timeout
            hub.EXTERNAL_REQUEST_TIMEOUT_MS = 100

            const result = await executor.executeFetch(invocation)

            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueScheduledAt).toMatchInlineSnapshot(`"2025-01-01T00:00:01.500Z"`)
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "HTTP fetch failed on attempt 1 with status code (none). Error: The operation was aborted due to timeout. Retrying in 1500ms.",
                ]
            `)
        })

        it('handles ResponseContentLengthMismatchError', async () => {
            jest.mocked(fetch).mockImplementationOnce(() => {
                const error = new Error('Response body length does not match content-length header')
                error.name = 'ResponseContentLengthMismatchError'
                return Promise.reject(error)
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
            })

            const result = await executor.executeFetch(invocation)

            expect(result.invocation.queue).toBe('hog')
            expect(result.invocation.queueScheduledAt).toBeUndefined() // Should not retry
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "HTTP fetch failed on attempt 1 with status code (none). Error: Response body length does not match content-length header.",
                ]
            `)
        })

        it('completes fetch with headers', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                if (req.headers['x-test'] === 'test') {
                    res.writeHead(200)
                } else {
                    res.writeHead(400)
                }
                res.end('Hello, world!')
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
                headers: {
                    'X-Test': 'test',
                },
            })

            const result = await executor.executeFetch(invocation)
            const response = result.invocation.state.vmState!.stack.slice(-1)[0]

            expect(result.invocation.queue).toBe('hog')
            expect(response).toMatchInlineSnapshot(`
                {
                  "body": "Hello, world!",
                  "status": 200,
                }
            `)
        })

        it('completes fetch with body', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                let body = ''
                req.on('data', (chunk: any) => {
                    body += chunk
                })
                req.on('end', () => {
                    expect(body).toBe('test body')
                    res.writeHead(200)
                    res.end('Hello, world!')
                })
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'POST',
                body: 'test body',
            })

            const result = await executor.executeFetch(invocation)
            const response = result.invocation.state.vmState!.stack.slice(-1)[0]

            expect(result.invocation.queue).toBe('hog')
            expect(response).toMatchInlineSnapshot(`
                {
                  "body": "Hello, world!",
                  "status": 200,
                }
            `)
        })

        it('handles minimum parameters', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                expect(req.method).toBe('GET')
                res.writeHead(200)
                res.end('Hello, world!')
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
            })

            const result = await executor.executeFetch(invocation)
            const response = result.invocation.state.vmState!.stack.slice(-1)[0]

            expect(result.invocation.queue).toBe('hog')
            expect(response).toMatchInlineSnapshot(`
                {
                  "body": "Hello, world!",
                  "status": 200,
                }
            `)
        })

        it('adds secret headers for certain endpoints', async () => {
            jest.mocked(fetch).mockImplementation(() => {
                return Promise.resolve({
                    status: 200,
                    body: 'Hello, world!',
                    headers: {},
                    json: () => Promise.resolve({}),
                    text: () => Promise.resolve(''),
                    dump: () => Promise.resolve(),
                })
            })

            hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN = 'ADWORDS_TOKEN'

            let invocation = await createFetchInvocation({
                url: 'https://googleads.googleapis.com/1234',
                method: 'POST',
                headers: {
                    'X-Test': 'test',
                },
            })

            await executor.executeFetch(invocation)
            expect((jest.mocked(fetch).mock.calls[0][1] as any).headers).toMatchInlineSnapshot(`
                {
                  "X-Test": "test",
                  "developer-token": "ADWORDS_TOKEN",
                }
            `)

            // Check it doesn't do it for redirect
            invocation = await createFetchInvocation({
                url: 'https://nasty.com?redirect=https://googleads.googleapis.com/1234',
                method: 'POST',
                headers: {
                    'X-Test': 'test',
                },
            })
            await executor.executeFetch(invocation)
            expect((jest.mocked(fetch).mock.calls[1][1] as any).headers).toMatchInlineSnapshot(`
                {
                  "X-Test": "test",
                }
            `)
        })

        it('replaces access token placeholders in body, headers, and url', async () => {
            const mockIntegrationInputs = {
                oauth: {
                    value: {
                        access_token_raw: 'actual_secret_token_12345',
                    },
                },
            }

            jest.spyOn(executor['hogInputsService'], 'loadIntegrationInputs').mockResolvedValue(mockIntegrationInputs)

            const invocation = createExampleInvocation()
            invocation.state.globals.inputs = mockIntegrationInputs
            invocation.hogFunction.inputs = {
                oauth: { value: 123 },
            }
            invocation.state.vmState = { stack: [] } as any
            invocation.queueParameters = {
                type: 'fetch',
                url: 'https://example.com/test?q=$$_access_token_placeholder_123',
                method: 'POST',
                headers: {
                    'X-Test': '$$_access_token_placeholder_123',
                    Authorization: 'Bearer $$_access_token_placeholder_123',
                },
                body: '$$_access_token_placeholder_123',
            } as any

            await executor.executeFetch(invocation)

            expect(jest.mocked(fetch).mock.calls[0] as any).toMatchInlineSnapshot(`
                [
                  "https://example.com/test?q=actual_secret_token_12345",
                  {
                    "body": "actual_secret_token_12345",
                    "headers": {
                      "Authorization": "Bearer actual_secret_token_12345",
                      "X-Test": "actual_secret_token_12345",
                    },
                    "method": "POST",
                  },
                ]
            `)
        })
    })
})
