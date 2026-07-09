// sort-imports-ignore
import { createServer } from 'http'
import { DateTime } from 'luxon'
import { AddressInfo } from 'net'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'

import { HogExecutorService } from '../../../src/cdp/services/hog-executor.service'
import { HogInputsService } from '../../../src/cdp/services/hog-inputs.service'
import { TeamWorkflowsConfigService } from '../../../src/cdp/services/managers/team-workflows-config.service'
import { EmailService } from '../../../src/cdp/services/messaging/email.service'
import { EmailTrackingCodeSigner } from '../../../src/cdp/services/messaging/helpers/tracking-code'
import { RecipientTokensService } from '../../../src/cdp/services/messaging/recipient-tokens.service'
import { CyclotronJobInvocationHogFunction, HogFunctionType } from '../../../src/cdp/types'
import { Hub } from '../../../src/types'
import { createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'
import { promisifyCallback } from '~/common/utils/utils'
import { compileHog } from '../templates/compiler'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createExampleInvocation, createHogExecutionGlobals, createHogFunction } from '../_tests/fixtures'
import { EXTEND_OBJECT_KEY, isConnectionLevelError } from './hog-executor.service'
import { SELF_LOOP_DEPTH_PROPERTY, selfLoopGuardCounter } from './self-loop-guard'

// Mock before importing fetch
jest.mock('~/common/utils/request', () => {
    const original = jest.requireActual('~/common/utils/request')
    return {
        ...original,
        fetch: jest.fn().mockImplementation((url, options) => {
            return original.fetch(url, options)
        }),
    }
})

import { fetch } from '~/common/utils/request'

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
        const hogInputsService = new HogInputsService(
            hub.integrationManager,
            new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL),
            hub.encryptedFields
        )
        const emailService = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
            },
            hub.integrationManager,
            new TeamWorkflowsConfigService(hub.postgres),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL)
        )
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        executor = new HogExecutorService(
            {
                hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
                fetchRetries: hub.CDP_FETCH_RETRIES,
                fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
                fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
                selfLoopGuardMode: hub.CDP_SELF_LOOP_GUARD_MODE,
            },
            { teamManager: hub.teamManager, siteUrl: hub.SITE_URL },
            hogInputsService,
            emailService,
            recipientTokensService,
            undefined as any
        )
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
                warehouseWebhookPayloads: [],
                emailAssets: [],
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
                url: `http://localhost:8000/projects/1/functions/${fn.id}/configuration/`,
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

        it('rebuilds mapping inputs when an invocation arrives without inputs (rerun path)', async () => {
            // The rerun path strips `inputs` from the persisted globals and lets
            // the executor rebuild them. For mapping destinations the mapping's
            // own inputs (e.g. Google Ads `gclid`) must be re-merged — otherwise
            // they resolve to nothing and the function early-exits on rerun.
            const hog = `return inputs.gclid`
            const mappingFn = createHogFunction({
                hog,
                bytecode: await compileHog(hog),
                ...HOG_FILTERS_EXAMPLES.no_filters,
                inputs_schema: [],
                mappings: [
                    {
                        ...HOG_FILTERS_EXAMPLES.no_filters,
                        inputs: {
                            gclid: {
                                order: 0,
                                value: '{person.properties.gclid ?? person.properties.$initial_gclid}',
                                bytecode: await compileHog(
                                    'return person.properties.gclid ?? person.properties.$initial_gclid'
                                ),
                            },
                        },
                    },
                ],
            })

            const invocation = createExampleInvocation(mappingFn, {
                person: {
                    id: 'uuid',
                    name: 'test',
                    url: 'http://localhost:8000/persons/1',
                    properties: { email: 'test@posthog.com', $initial_gclid: 'INITIAL_TOKEN_ABC' },
                },
            })
            // Simulate the rerun blob: inputs are stripped before persistence.
            expect(invocation.state.globals.inputs).toBeUndefined()

            const res = await executor.execute(invocation)
            expect(res.error).toBeUndefined()
            expect(res.execResult).toBe('INITIAL_TOKEN_ABC')
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
            })

            const res = await executor.execute(createExampleInvocation(fn))
            expect(res.finished).toBe(true)
            expect(res.execResult).toBeUndefined()
            expect(cleanLogs(res.logs.map((x) => x.message))).toEqual([
                "Function completed in REPLACEDms. Sync: 0ms. Mem: 0.17kb. Ops: 28. Event: 'http://localhost:8000/events/1'",
            ])
        })

        it('sets execResult when VM returns an object synchronously', async () => {
            // This tests a simple return statement without any async functions
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_return_object,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const res = await executor.execute(createExampleInvocation(fn))
            expect(res.finished).toBe(true)
            expect(res.execResult).toEqual({
                status: 'pending',
                priority: 'high',
                ticket_number: 42,
            })
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

        it('falls back to person.id for distinct_id when event.distinct_id is empty (batch invocations)', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({
                groups: {},
                event: {
                    distinct_id: '',
                } as any,
                person: {
                    id: 'person-uuid-123',
                    name: 'Batch Person',
                    url: 'http://localhost:8000/persons/1',
                    properties: { email: 'batch@posthog.com' },
                },
            } as any)
            const result = await executor.execute(createExampleInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toHaveLength(1)
            expect(result?.capturedPostHogEvents[0].distinct_id).toBe('person-uuid-123')
        })

        it('allows events that have already used their postHogCapture a maximum of 10 times', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({
                groups: {},
                event: {
                    properties: {
                        $hog_function_execution_count: 9,
                    },
                },
            } as any)
            const result = await executor.execute(createExampleInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toMatchInlineSnapshot(`
                [
                  {
                    "distinct_id": "distinct_id",
                    "event": "test (copy)",
                    "properties": {
                      "$hog_function_execution_count": 10,
                    },
                    "team_id": 1,
                    "timestamp": "2025-01-01T00:00:00.000Z",
                  },
                ]
            `)
        })

        it('ignores events that have already used their postHogCapture 10 times', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.posthog_capture,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({
                groups: {},
                event: {
                    properties: {
                        $hog_function_execution_count: 10,
                    },
                },
            } as any)
            const result = await executor.execute(createExampleInvocation(fn, globals))
            expect(result?.capturedPostHogEvents).toEqual([])
            expect(cleanLogs(result?.logs.map((log) => log.message) ?? [])).toMatchInlineSnapshot(`
                [
                  "postHogCapture was called from an event that already executed this function 10 times previously. To prevent unbounded infinite loops, the event was not captured.",
                  "Function completed in REPLACEDms. Sync: 0ms. Mem: 0.1kb. Ops: 15. Event: 'http://localhost:8000/events/1'",
                ]
            `)
        })
    })

    describe('postHogGetTicket and postHogUpdateTicket', () => {
        const mockExecHogForAsyncFunction = (asyncFunctionName: string, asyncFunctionArgs: any[]) => {
            const hogExecModule = require('../utils/hog-exec')
            jest.spyOn(hogExecModule, 'execHog').mockResolvedValue({
                execResult: {
                    finished: false,
                    asyncFunctionName,
                    asyncFunctionArgs,
                    state: { syncDuration: 1, maxMemUsed: 100, ops: 10, stack: [] },
                },
                error: undefined,
                durationMs: 1,
            })
        }

        // Provide pre-built inputs so buildInputsWithGlobals is skipped
        const createTicketInvocation = () =>
            createExampleInvocation(
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                }),
                { inputs: {} }
            )

        it('postHogGetTicket queues internal fetch with correct params', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogGetTicket', [{ ticket_id: 'test-ticket-123' }])

            const result = await executor.execute(createTicketInvocation())

            expect(result.invocation.queueParameters).toEqual({
                type: 'fetch',
                url: `${hub.SITE_URL}/api/conversations/external/ticket/test-ticket-123`,
                method: 'GET',
                headers: { Authorization: 'Bearer test-secret-token' },
            })
        })

        it('postHogUpdateTicket queues internal fetch with correct params', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogUpdateTicket', [
                { ticket_id: 'test-ticket-456', updates: { status: 'resolved', priority: 'high' } },
            ])

            const result = await executor.execute(createTicketInvocation())

            expect(result.invocation.queueParameters).toEqual({
                type: 'fetch',
                url: `${hub.SITE_URL}/api/conversations/external/ticket/test-ticket-456`,
                method: 'PATCH',
                body: JSON.stringify({ status: 'resolved', priority: 'high' }),
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: 'Bearer test-secret-token',
                },
            })
        })

        it('postHogGetTicket errors when ticket_id is missing', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogGetTicket', [{}])

            const result = await executor.execute(createTicketInvocation())
            expect(result.error).toContain("missing 'ticket_id'")
        })

        it('postHogUpdateTicket errors when ticket_id is missing', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogUpdateTicket', [{ updates: { status: 'resolved' } }])

            const result = await executor.execute(createTicketInvocation())
            expect(result.error).toContain("missing 'ticket_id'")
        })

        it('postHogGetTicket errors when team is not found', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue(null)

            mockExecHogForAsyncFunction('postHogGetTicket', [{ ticket_id: 'test-ticket-123' }])

            const result = await executor.execute(createTicketInvocation())
            expect(result.error).toContain('Team 1 not found')
        })
    })

    describe('postHogGetAccount', () => {
        const mockExecHogForAsyncFunction = (asyncFunctionName: string, asyncFunctionArgs: any[]) => {
            const hogExecModule = require('../utils/hog-exec')
            jest.spyOn(hogExecModule, 'execHog').mockResolvedValue({
                execResult: {
                    finished: false,
                    asyncFunctionName,
                    asyncFunctionArgs,
                    state: { syncDuration: 1, maxMemUsed: 100, ops: 10, stack: [] },
                },
                error: undefined,
                durationMs: 1,
            })
        }

        const createAccountInvocation = () =>
            createExampleInvocation(
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                }),
                { inputs: {} }
            )

        it('postHogGetAccount queues internal fetch with the external_id query param', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogGetAccount', [{ external_id: 'acme corp/1' }])

            const result = await executor.execute(createAccountInvocation())

            expect(result.invocation.queueParameters).toEqual({
                type: 'fetch',
                url: `${hub.SITE_URL}/api/customer_analytics/external/account?external_id=acme%20corp%2F1`,
                method: 'GET',
                headers: { Authorization: 'Bearer test-secret-token' },
            })
        })

        it('postHogGetAccount errors when external_id is missing', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogGetAccount', [{}])

            const result = await executor.execute(createAccountInvocation())
            expect(result.error).toContain("missing 'external_id'")
        })

        it('postHogGetAccount errors when team is not found', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue(null)

            mockExecHogForAsyncFunction('postHogGetAccount', [{ external_id: 'acme-1' }])

            const result = await executor.execute(createAccountInvocation())
            expect(result.error).toContain('Team 1 not found')
        })

        it('postHogGetAccount errors when the team has no secret API token', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: null,
            } as any)

            mockExecHogForAsyncFunction('postHogGetAccount', [{ external_id: 'acme-1' }])

            const result = await executor.execute(createAccountInvocation())
            expect(result.error).toContain('has no secret API token configured')
        })

        it('captures exception with team_id when secret API token is missing', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: null,
            } as any)

            const posthogModule = require('~/common/utils/posthog')
            const captureExceptionSpy = jest.spyOn(posthogModule, 'captureException')

            mockExecHogForAsyncFunction('postHogGetAccount', [{ external_id: 'acme-1' }])
            await executor.execute(createAccountInvocation())

            expect(captureExceptionSpy).toHaveBeenCalledWith(
                expect.any(Error),
                expect.objectContaining({ tags: expect.objectContaining({ team_id: 1 }) })
            )
        })

        it('does not capture exception when queue is set up successfully', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            const posthogModule = require('~/common/utils/posthog')
            const captureExceptionSpy = jest.spyOn(posthogModule, 'captureException')

            mockExecHogForAsyncFunction('postHogGetAccount', [{ external_id: 'acme-1' }])
            await executor.execute(createAccountInvocation())

            expect(captureExceptionSpy).not.toHaveBeenCalled()
        })

        it('postHogUpdateAccount queues a PATCH with external_id merged into the body', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogUpdateAccount', [
                { external_id: 'acme-1', updates: { tags: ['enterprise'], tags_mode: 'add' } },
            ])

            const result = await executor.execute(createAccountInvocation())

            expect(result.invocation.queueParameters).toEqual({
                type: 'fetch',
                url: `${hub.SITE_URL}/api/customer_analytics/external/account`,
                method: 'PATCH',
                body: JSON.stringify({ external_id: 'acme-1', tags: ['enterprise'], tags_mode: 'add' }),
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: 'Bearer test-secret-token',
                },
            })
        })

        it('postHogUpdateAccount errors when external_id is missing', async () => {
            jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                id: 1,
                secret_api_token: 'test-secret-token',
            } as any)

            mockExecHogForAsyncFunction('postHogUpdateAccount', [{ updates: { tags: ['enterprise'] } }])

            const result = await executor.execute(createAccountInvocation())
            expect(result.error).toContain("missing 'external_id'")
        })
    })

    describe('produceToWarehouseWebhooks', () => {
        const buildInvocation = async (code: string): Promise<CyclotronJobInvocationHogFunction> => {
            const bytecode = await compileHog(code)
            return createExampleInvocation(createHogFunction({ bytecode }), { inputs: {} })
        }

        // Regression test for a stack-empty crash when an async function with no
        // meaningful return value is called as an expression statement.
        // The bytecode compiler emits a trailing POP after every expression
        // statement, but the generic async function path in execute() never pushed
        // a return value onto the resumed VM stack — so when the cyclotron worker
        // resumed the invocation, the POP fired against an empty stack and raised
        // "Invalid HogQL bytecode, stack is empty, can not pop".
        it('finishes cleanly when called as an expression statement', async () => {
            const invocation = await buildInvocation(`produceToWarehouseWebhooks({'foo': 'bar'}, 'test-schema-id')`)

            const result = await executor.executeWithAsyncFunctions(invocation)

            expect(result.error).toBeUndefined()
            expect(result.finished).toBe(true)
            expect(result.warehouseWebhookPayloads).toHaveLength(1)
            expect(result.warehouseWebhookPayloads[0]).toMatchObject({
                schema_id: 'test-schema-id',
                payload: { foo: 'bar' },
            })
        })

        it('finishes cleanly when followed by another statement', async () => {
            const invocation = await buildInvocation(
                `produceToWarehouseWebhooks({'foo': 'bar'}, 'test-schema-id')
                 print('after produce')`
            )

            const result = await executor.executeWithAsyncFunctions(invocation)

            expect(result.error).toBeUndefined()
            expect(result.finished).toBe(true)
            expect(result.warehouseWebhookPayloads).toHaveLength(1)
        })
    })

    describe('fetch does not allow internal flag', () => {
        it('regular fetch call does not pass through internal flag', async () => {
            const invocation = createExampleInvocation(
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                })
            )

            const result = await executor.execute(invocation)

            // The fetch case handler only picks url/method/body/headers — internal is never passed
            expect(result.invocation.queueParameters).toBeDefined()
            expect((result.invocation.queueParameters as any).type).toBe('fetch')
            expect((result.invocation.queueParameters as any).internal).toBeUndefined()
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

        it('sets result.error after retries are exhausted', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                res.writeHead(500, { 'Content-Type': 'text/plain' })
                res.end('server error')
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
            })

            const maxRetries = executor['config'].fetchRetries
            let result = await executor.executeFetch(invocation)

            for (let attempt = 1; attempt < maxRetries; attempt++) {
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.attempts).toBe(attempt)
                expect(result.invocation.queueScheduledAt).toBeDefined()
                result = await executor.executeFetch(result.invocation)
            }

            expect(result.error).toBeInstanceOf(Error)
            expect(result.error.message).toContain(`HTTP fetch failed on attempt ${maxRetries}`)
            expect(result.error.message).toContain('with status code 500')
            expect(result.invocation.queueScheduledAt).toBeUndefined()
        })

        describe('aws_sigv4', () => {
            // `secret: true` HogFunction inputs land in `encrypted_inputs` after
            // Django's `move_secret_inputs` runs on save. The Node manager decrypts
            // `encrypted_inputs` in memory before the executor sees the function, so
            // by the time we reach the fetch path it's a plaintext map keyed by
            // input name. Seed *that* field — not `inputs` — so the tests mirror the
            // production data shape for the Kinesis template.
            const seedAwsCredentialInputs = (invocation: CyclotronJobInvocationHogFunction) => {
                invocation.hogFunction.encrypted_inputs = {
                    ...(invocation.hogFunction.encrypted_inputs ?? {}),
                    aws_access_key_id: { value: 'AKIDEXAMPLE' },
                    aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
                } as any
            }

            const sigv4Refs = {
                service: 'kinesis',
                region: 'us-east-1',
                access_key_id_input: 'aws_access_key_id',
                secret_access_key_input: 'aws_secret_access_key',
            }

            it('signs the request and Authorization header arrives at the upstream', async () => {
                let receivedAuth: string | undefined
                let receivedAmzDate: string | undefined
                mockRequest.mockImplementation((req: any, res: any) => {
                    receivedAuth = req.headers.authorization
                    receivedAmzDate = req.headers['x-amz-date']
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end('ok')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/`,
                    method: 'POST',
                    body: '{}',
                    headers: { 'Content-Type': 'application/x-amz-json-1.1' },
                    aws_sigv4: sigv4Refs,
                })
                seedAwsCredentialInputs(invocation)

                await executor.executeFetch(invocation)

                expect(receivedAmzDate).toBe('20250101T000000Z')
                expect(receivedAuth).toMatch(
                    /^AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE\/20250101\/us-east-1\/kinesis\/aws4_request, SignedHeaders=[a-z0-9;-]+, Signature=[a-f0-9]{64}$/
                )
            })

            // Customer impact this prevents: the original bug ticket had a request
            // signed at T, queued behind a timed-out attempt, then retried >5 min
            // later — AWS rejected the retry with InvalidSignatureException because
            // the X-Amz-Date inside the Authorization no longer matched server time.
            it('produces a fresh signature on retry instead of reusing the original', async () => {
                const receivedAuthHeaders: string[] = []
                const receivedAmzDates: string[] = []
                let callCount = 0
                mockRequest.mockImplementation((req: any, res: any) => {
                    receivedAuthHeaders.push(req.headers.authorization)
                    receivedAmzDates.push(req.headers['x-amz-date'])
                    callCount++
                    if (callCount === 1) {
                        res.writeHead(500, { 'Content-Type': 'text/plain' })
                        res.end('first attempt fails')
                    } else {
                        res.writeHead(200, { 'Content-Type': 'text/plain' })
                        res.end('second attempt ok')
                    }
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/`,
                    method: 'POST',
                    body: '{}',
                    headers: { 'Content-Type': 'application/x-amz-json-1.1' },
                    aws_sigv4: sigv4Refs,
                })
                seedAwsCredentialInputs(invocation)

                let result = await executor.executeFetch(invocation)
                expect(result.invocation.state.attempts).toBe(1)

                // Simulate the cyclotron queue + backoff: by the time the retry
                // actually runs, >6 minutes have passed. With the old "sign once
                // in Hog" path this would push the signature past AWS's 5-minute
                // window and the retry would 400 with InvalidSignatureException.
                const retryTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' }).plus({
                    minutes: 6,
                })
                jest.spyOn(Date, 'now').mockReturnValue(retryTime.toMillis())

                result = await executor.executeFetch(result.invocation)

                expect(receivedAmzDates[0]).toBe('20250101T000000Z')
                expect(receivedAmzDates[1]).toBe('20250101T000600Z')
                expect(receivedAuthHeaders[0]).not.toBe(receivedAuthHeaders[1])
                expect(result.error).toBeUndefined()
            })

            // Defense in depth: queue payloads should never carry a stale
            // Authorization, but if one ever leaks in (e.g. through a custom
            // template that sets it directly), it must not be used.
            it('overwrites any stale Authorization header sitting in the queue payload', async () => {
                let receivedAuth: string | undefined
                mockRequest.mockImplementation((req: any, res: any) => {
                    receivedAuth = req.headers.authorization
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end('ok')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/`,
                    method: 'POST',
                    body: '{}',
                    headers: {
                        'Content-Type': 'application/x-amz-json-1.1',
                        Authorization: 'AWS4-HMAC-SHA256 Credential=STALE/19700101/us-east-1/kinesis/aws4_request, ...',
                        'X-Amz-Date': '19700101T000000Z',
                    },
                    aws_sigv4: sigv4Refs,
                })
                seedAwsCredentialInputs(invocation)

                await executor.executeFetch(invocation)

                expect(receivedAuth).not.toContain('STALE')
                expect(receivedAuth).toContain('AKIDEXAMPLE/20250101/us-east-1/kinesis/aws4_request')
            })

            // Defense in depth for an unusual case: if a custom template wires
            // up the credential as a non-secret input (`secret: false`), the value
            // will live on `inputs` rather than `encrypted_inputs`. The lookup
            // must fall through to `inputs` so signing still works.
            it('falls back to plaintext inputs when encrypted_inputs does not carry the credential', async () => {
                let receivedAuth: string | undefined
                mockRequest.mockImplementation((req: any, res: any) => {
                    receivedAuth = req.headers.authorization
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end('ok')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/`,
                    method: 'POST',
                    body: '{}',
                    headers: { 'Content-Type': 'application/x-amz-json-1.1' },
                    aws_sigv4: sigv4Refs,
                })
                invocation.hogFunction.inputs = {
                    ...(invocation.hogFunction.inputs ?? {}),
                    aws_access_key_id: { value: 'AKIDEXAMPLE' },
                    aws_secret_access_key: { value: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY' },
                } as any

                await executor.executeFetch(invocation)

                expect(receivedAuth).toContain('AKIDEXAMPLE/20250101/us-east-1/kinesis/aws4_request')
            })

            // If the input referenced by `*_input` is missing or non-string we must
            // NOT fall through and ship an unsigned request to AWS — that'd 403 and
            // potentially leak the request body in error logs.
            it('errors loudly when the referenced credential input is missing', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end('ok')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/`,
                    method: 'POST',
                    body: '{}',
                    headers: { 'Content-Type': 'application/x-amz-json-1.1' },
                    aws_sigv4: sigv4Refs,
                })
                // Intentionally do NOT seed inputs.

                const result = await executor.executeFetch(invocation)

                expect(mockRequest).not.toHaveBeenCalled()
                expect(result.error).toBeInstanceOf(Error)
                expect(result.error.message).toContain('AWS SigV4 signing failed')
                expect(result.error.message).toContain('aws_access_key_id')
                expect(result.error.message).toContain('aws_secret_access_key')
            })
        })

        it('respects maxFetchRetries option to disable retries', async () => {
            mockRequest.mockImplementation((req: any, res: any) => {
                res.writeHead(500, { 'Content-Type': 'text/plain' })
                res.end('server error')
            })

            const invocation = await createFetchInvocation({
                url: `${baseUrl}/test`,
                method: 'GET',
            })

            const result = await executor.executeWithAsyncFunctions(invocation, { maxFetchRetries: 0 })

            expect(result.finished).toBe(true)
            expect(result.error).toBeInstanceOf(Error)
            expect(result.error!.message).toContain('HTTP fetch failed on attempt 1')
            expect(result.invocation.queueScheduledAt).toBeUndefined()
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

            // Should not be scheduled for retry
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

            executor['config'].googleAdwordsDeveloperToken = 'ADWORDS_TOKEN'

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

        describe('with non_failure_status_codes', () => {
            beforeEach(() => {
                const actualRequest = jest.requireActual('~/common/utils/request') as { fetch: typeof fetch }
                jest.mocked(fetch).mockImplementation((url, options) => actualRequest.fetch(url, options))
            })

            const setNonFailureConfig = (
                invocation: CyclotronJobInvocationHogFunction,
                value: Array<number | string>
            ): void => {
                invocation.hogFunction.inputs_schema = [
                    ...(invocation.hogFunction.inputs_schema ?? []),
                    {
                        key: 'non_failure_status_codes',
                        type: 'non_failure_status_codes',
                        label: 'Non-failure response codes',
                        required: false,
                    },
                ]
                invocation.hogFunction.inputs = {
                    ...(invocation.hogFunction.inputs ?? {}),
                    non_failure_status_codes: { value },
                }
            }

            it('treats matched non-retriable 4xx as success (exact match)', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(400, { 'Content-Type': 'text/plain' })
                    res.end('backdated consent')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'GET',
                })
                setNonFailureConfig(invocation, [400])

                const result = await executor.executeFetch(invocation)

                expect(result.error).toBeUndefined()
                expect(result.invocation.queueScheduledAt).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({
                    status: 400,
                    body: 'backdated consent',
                })
                expect(result.logs.map((l) => ({ level: l.level, message: l.message }))).toEqual([
                    {
                        level: 'info',
                        message: expect.stringContaining('status code 400'),
                    },
                ])
            })

            it('treats matched 4xx as success via wildcard', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(404, { 'Content-Type': 'text/plain' })
                    res.end('not found')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'GET',
                })
                setNonFailureConfig(invocation, ['4xx'])

                const result = await executor.executeFetch(invocation)

                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({
                    status: 404,
                    body: 'not found',
                })
            })

            it('does not match when ignore list does not cover the status', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(401, { 'Content-Type': 'text/plain' })
                    res.end('unauthorized')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'GET',
                })
                setNonFailureConfig(invocation, [400, 403])

                const result = await executor.executeFetch(invocation)

                expect(result.error).toBeInstanceOf(Error)
                expect(result.error.message).toContain('status code 401')
                expect(result.logs[0].level).toBe('error')
            })

            it('still retries a retriable status that is in the ignore list, then succeeds without setting result.error', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(500, { 'Content-Type': 'text/plain' })
                    res.end('server error')
                })

                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'GET',
                })
                setNonFailureConfig(invocation, [500])

                const maxRetries = executor['config'].fetchRetries
                let result = await executor.executeFetch(invocation)
                // Verify every intermediate attempt also logged at 'info' — regression guard
                // against any future change that re-raises retry logs to 'error' when the
                // status is in the non-failure list.
                expect(result.logs.every((l) => l.level === 'info')).toBe(true)

                for (let attempt = 1; attempt < maxRetries; attempt++) {
                    expect(result.error).toBeUndefined()
                    expect(result.invocation.queueScheduledAt).not.toBeUndefined()
                    expect(result.invocation.state.attempts).toBe(attempt)
                    result = await executor.executeFetch(result.invocation)
                    expect(result.logs.every((l) => l.level === 'info')).toBe(true)
                }

                expect(result.error).toBeUndefined()
                expect(result.invocation.queueScheduledAt).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({
                    status: 500,
                    body: 'server error',
                })
                expect(result.logs.every((l) => l.level === 'info')).toBe(true)
            })

            it('mixed wildcard and number ignores both 4xx and the specific 5xx', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(404, { 'Content-Type': 'text/plain' })
                    res.end('a')
                })
                let invocation = await createFetchInvocation({ url: `${baseUrl}/test`, method: 'GET' })
                setNonFailureConfig(invocation, ['4xx', 500])

                let result = await executor.executeFetch(invocation)
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({ status: 404, body: 'a' })

                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(500, { 'Content-Type': 'text/plain' })
                    res.end('b')
                })
                invocation = await createFetchInvocation({ url: `${baseUrl}/test`, method: 'GET' })
                setNonFailureConfig(invocation, ['4xx', 500])

                // 500 is retriable — drain retries until terminal
                const maxRetries = executor['config'].fetchRetries
                result = await executor.executeFetch(invocation)
                for (let attempt = 1; attempt < maxRetries; attempt++) {
                    result = await executor.executeFetch(result.invocation)
                }
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({ status: 500, body: 'b' })
            })

            it('does not ignore a 502 when config is [4xx, 500]', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(502, { 'Content-Type': 'text/plain' })
                    res.end('bad gateway')
                })
                const invocation = await createFetchInvocation({ url: `${baseUrl}/test`, method: 'GET' })
                setNonFailureConfig(invocation, ['4xx', 500])

                const maxRetries = executor['config'].fetchRetries
                let result = await executor.executeFetch(invocation)
                for (let attempt = 1; attempt < maxRetries; attempt++) {
                    result = await executor.executeFetch(result.invocation)
                }
                expect(result.error).toBeInstanceOf(Error)
                expect(result.error.message).toContain('status code 502')
            })

            it('does not affect successful responses', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(200, { 'Content-Type': 'text/plain' })
                    res.end('ok')
                })
                const invocation = await createFetchInvocation({ url: `${baseUrl}/test`, method: 'GET' })
                setNonFailureConfig(invocation, ['4xx', 500])

                const result = await executor.executeFetch(invocation)
                expect(result.error).toBeUndefined()
                expect(result.invocation.state.vmState!.stack.slice(-1)[0]).toEqual({ status: 200, body: 'ok' })
            })

            it('is a no-op when ignore config is empty', async () => {
                mockRequest.mockImplementation((req: any, res: any) => {
                    res.writeHead(400, { 'Content-Type': 'text/plain' })
                    res.end('bad')
                })
                const invocation = await createFetchInvocation({ url: `${baseUrl}/test`, method: 'GET' })
                setNonFailureConfig(invocation, [])

                const result = await executor.executeFetch(invocation)
                expect(result.error).toBeInstanceOf(Error)
                expect(result.error.message).toContain('status code 400')
            })
        })

        describe('self-loop guard', () => {
            const OWN_TOKEN = 'phc_synthetic_own_0000000000000000'
            const INGEST_URL = 'https://us.i.posthog.com/capture/'

            const mockOwnTeam = (): void => {
                jest.spyOn(hub.teamManager, 'getTeam').mockResolvedValue({
                    id: 1,
                    api_token: OWN_TOKEN,
                    secret_api_token: null,
                } as any)
            }

            const setMode = (mode: 'disabled' | 'warn' | 'enforce'): void => {
                ;(executor as any).config.selfLoopGuardMode = mode
            }

            const ownTokenCaptureBody = (): string =>
                JSON.stringify({ api_key: OWN_TOKEN, event: 'replicated', distinct_id: 'u1', properties: {} })

            // Seed this destination's own self-loop depth (keyed by its function id).
            const setSelfLoopDepth = (invocation: CyclotronJobInvocationHogFunction, depth: number): void => {
                invocation.state.globals.event.properties = {
                    ...invocation.state.globals.event.properties,
                    [SELF_LOOP_DEPTH_PROPERTY]: { [invocation.hogFunction.id]: depth },
                }
            }

            // Seed a high depth for a DIFFERENT function - simulates an event that passed
            // through an unrelated deep chain. Must not count toward this destination.
            const setOtherFunctionDepth = (invocation: CyclotronJobInvocationHogFunction, depth: number): void => {
                invocation.state.globals.event.properties = {
                    ...invocation.state.globals.event.properties,
                    [SELF_LOOP_DEPTH_PROPERTY]: { 'some-other-function-id': depth },
                }
            }

            // Capture the body sent to the (mocked) ingest endpoint without a real network call.
            const captureIngestFetch = (): { getBody: () => string | undefined } => {
                let sentBody: string | undefined
                ;(fetch as jest.Mock).mockImplementationOnce((_url: string, options: any) => {
                    sentBody = options.body
                    return Promise.resolve({ status: 200, headers: {}, text: () => Promise.resolve('ok') })
                })
                return { getBody: () => sentBody }
            }

            const readActionCount = async (mode: string, action: string): Promise<number> => {
                const metric = await selfLoopGuardCounter.get()
                return metric.values.find((v) => v.labels.mode === mode && v.labels.action === action)?.value ?? 0
            }

            // The detected count is the production signal that drives the enforce decision,
            // so assert it actually moves - not just the human-facing log.
            const readDetectedCount = (): Promise<number> => readActionCount('warn', 'detected')

            it('detects a self-referential ingest fetch and logs + meters it without blocking (warn)', async () => {
                setMode('warn')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: INGEST_URL,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                ;(fetch as jest.Mock).mockImplementationOnce(() =>
                    Promise.resolve({ status: 200, headers: {}, text: () => Promise.resolve('ok') })
                )
                const detectedBefore = await readDetectedCount()

                const result = await executor.executeFetch(invocation)

                // Observe-only: the fetch still happens and nothing errors.
                expect(result.error).toBeUndefined()
                expect(cleanLogs(result.logs.map((l) => l.message))).toEqual(
                    expect.arrayContaining([expect.stringContaining('can form an event-forwarding loop')])
                )
                expect(await readDetectedCount()).toBe(detectedBefore + 1)
            })

            it('does not flag a normal external fetch even with the project token in the body', async () => {
                setMode('warn')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                mockRequest.mockClear()
                const detectedBefore = await readDetectedCount()

                const result = await executor.executeFetch(invocation)

                expect(result.error).toBeUndefined()
                expect(mockRequest).toHaveBeenCalled()
                expect(cleanLogs(result.logs.map((l) => l.message))).not.toEqual(
                    expect.arrayContaining([expect.stringContaining('event-forwarding loop')])
                )
                expect(await readDetectedCount()).toBe(detectedBefore)
            })

            it('fails open: a team lookup error never breaks the fetch', async () => {
                setMode('warn')
                jest.spyOn(hub.teamManager, 'getTeam').mockRejectedValue(new Error('db unavailable'))
                const invocation = await createFetchInvocation({
                    url: INGEST_URL,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                ;(fetch as jest.Mock).mockImplementationOnce(() =>
                    Promise.resolve({ status: 200, headers: {}, text: () => Promise.resolve('ok') })
                )

                const result = await executor.executeFetch(invocation)

                // Detection failing must not surface as a destination error.
                expect(result.error).toBeUndefined()
            })

            // Every hop under the cap is allowed and its outgoing body stamped with this
            // destination's next depth - including hop 0 (a fresh external event), which a
            // legitimate run always is.
            it.each([
                { case: 'fresh hop 0 (a legitimate external run)', depth: 0, stampedTo: 1 },
                { case: 'mid-chain under the cap', depth: 2, stampedTo: 3 },
                { case: 'the last hop under the cap', depth: 9, stampedTo: 10 },
            ])('enforce: allows + stamps the next hop ($case)', async ({ depth, stampedTo }) => {
                setMode('enforce')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: INGEST_URL,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                setSelfLoopDepth(invocation, depth)
                const sent = captureIngestFetch()
                const blockedBefore = await readActionCount('enforce', 'blocked')

                const result = await executor.executeFetch(invocation)

                // Fetch proceeds, body carries this destination's incremented depth, nothing blocked.
                expect(result.error).toBeUndefined()
                expect(parseJSON(sent.getBody()!).properties[SELF_LOOP_DEPTH_PROPERTY][invocation.hogFunction.id]).toBe(
                    stampedTo
                )
                expect(await readActionCount('enforce', 'blocked')).toBe(blockedBefore)
            })

            // The whole point of per-function depth: an event that arrived carrying a huge
            // depth for a DIFFERENT function is treated as depth 0 here, so a legitimately
            // running destination is never blocked by an unrelated deep chain.
            it('enforce: does NOT block when the high depth belongs to another function', async () => {
                setMode('enforce')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: INGEST_URL,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                setOtherFunctionDepth(invocation, 50)
                const sent = captureIngestFetch()
                const blockedBefore = await readActionCount('enforce', 'blocked')

                const result = await executor.executeFetch(invocation)

                // Allowed, stamped as this destination's first hop, not blocked.
                expect(result.error).toBeUndefined()
                expect(parseJSON(sent.getBody()!).properties[SELF_LOOP_DEPTH_PROPERTY][invocation.hogFunction.id]).toBe(
                    1
                )
                expect(await readActionCount('enforce', 'blocked')).toBe(blockedBefore)
            })

            it('enforce: breaks the chain once it reaches the cap', async () => {
                setMode('enforce')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: INGEST_URL,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                setSelfLoopDepth(invocation, 10)
                mockRequest.mockClear()
                const blockedBefore = await readActionCount('enforce', 'blocked')

                const result = await executor.executeFetch(invocation)

                // Blocked: error set, finished, no fetch attempted, metric moved.
                expect(result.error).toBeInstanceOf(Error)
                expect(result.finished).toBe(true)
                expect(mockRequest).not.toHaveBeenCalled()
                expect(await readActionCount('enforce', 'blocked')).toBe(blockedBefore + 1)
                expect(cleanLogs(result.logs.map((l) => l.message))).toEqual(
                    expect.arrayContaining([expect.stringContaining('event-forwarding loop has already repeated')])
                )
            })

            it('enforce: leaves a normal external fetch untouched', async () => {
                setMode('enforce')
                mockOwnTeam()
                const invocation = await createFetchInvocation({
                    url: `${baseUrl}/test`,
                    method: 'POST',
                    body: ownTokenCaptureBody(),
                })
                mockRequest.mockClear()

                const result = await executor.executeFetch(invocation)

                expect(result.error).toBeUndefined()
                expect(mockRequest).toHaveBeenCalled()
            })
        })
    })

    describe('isConnectionLevelError', () => {
        it.each([
            [{ code: 'UND_ERR_SOCKET', message: 'other side closed' }, true],
            [{ code: 'ECONNRESET', message: 'read ECONNRESET' }, true],
            [{ code: 'EPIPE', message: 'write EPIPE' }, true],
            [{ code: undefined, message: 'other side closed' }, true],
            [{ code: undefined, message: 'socket hang up' }, true],
            [{ code: 'ENOTFOUND', message: 'getaddrinfo ENOTFOUND' }, false],
            [{ code: undefined, message: 'some other error' }, false],
            [null, false],
            [undefined, false],
        ])('returns %s for %j', (error, expected) => {
            expect(isConnectionLevelError(error)).toBe(expected)
        })
    })

    describe('routeEmailToQueue', () => {
        it('should route the invocation to the email queue', () => {
            const hogFunction = createHogFunction({
                name: 'Email function',
                metadata: { message_category_type: 'marketing' },
            })

            const invocation: CyclotronJobInvocationHogFunction = {
                ...createExampleInvocation(hogFunction),
                queue: 'hogflow',
                queueParameters: {
                    type: 'email',
                    to: { email: 'user@example.com' },
                    from: { integrationId: 1 },
                    subject: 'Test',
                    text: 'Hello',
                    html: '<p>Hello</p>',
                },
            }
            invocation.state.vmState = { stack: [] } as any

            const result = (executor as any).routeEmailToQueue(invocation)

            expect(result.finished).toBe(false)
            expect(result.invocation.queue).toBe('email')
            expect(result.invocation.queueMetadata?.originQueue).toBe('hogflow')
            expect(result.metrics).toContainEqual(
                expect.objectContaining({
                    metric_name: 'email_queued',
                    metric_kind: 'email',
                })
            )
        })

        it('should preserve the same job ID (no new job created)', () => {
            const hogFunction = createHogFunction({ name: 'Email function' })
            const invocation: CyclotronJobInvocationHogFunction = {
                ...createExampleInvocation(hogFunction),
                queueParameters: {
                    type: 'email',
                    to: { email: 'user@example.com' },
                    from: { integrationId: 1 },
                    subject: 'Test',
                    text: 'Hello',
                    html: '<p>Hello</p>',
                },
            }
            invocation.state.vmState = { stack: [] } as any

            const result = (executor as any).routeEmailToQueue(invocation)

            expect(result.invocation.id).toBe(invocation.id)
        })
    })

    describe('email queue routing', () => {
        const createEmailInvocation = (): CyclotronJobInvocationHogFunction => {
            const hogFunction = createHogFunction({ name: 'Email function', team_id: 123 })
            const invocation: CyclotronJobInvocationHogFunction = {
                ...createExampleInvocation(hogFunction),
                teamId: 123,
                queueParameters: {
                    type: 'email',
                    to: { email: 'user@example.com' },
                    from: { integrationId: 1 },
                    subject: 'Test',
                    text: 'Hello',
                    html: '<p>Hello</p>',
                },
            }
            invocation.state.vmState = { stack: [] } as any
            return invocation
        }

        it('should route email sends to the dedicated email queue', async () => {
            const invocation = createEmailInvocation()

            const result = await executor.executeWithAsyncFunctions(invocation)

            expect(result.invocation.queue).toBe('email')
            expect(result.invocation.queueMetadata?.originQueue).toBeDefined()
            expect(result.finished).toBe(false)
        })

        it('should send inline when sendEmailsInline is set', async () => {
            const invocation = createEmailInvocation()

            const result = await executor.executeWithAsyncFunctions(invocation, { sendEmailsInline: true })

            expect(result.invocation.queue).not.toBe('email')
            expect(result.finished).toBe(true)
        })
    })
})
