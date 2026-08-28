import { DateTime } from 'luxon'

import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../_tests/examples'
import { createHogExecutionGlobals, createHogFunction } from '../_tests/fixtures'
import { HogInputsService } from '../services/hog-inputs.service'
import { buildHogFunctionInvocations, cloneInvocation, createInvocation } from './invocation-utils'

describe('Invocation utils', () => {
    describe('buildHogFunctionInvocations', () => {
        // Plain templated inputs only: no integration, email or push_subscription schema types, so
        // the service never reaches its integration manager, tokens service or encrypted fields.
        const hogInputsService = new HogInputsService(undefined as any, undefined as any, undefined as any)

        const pageviewGlobals = () =>
            createHogExecutionGlobals({
                groups: {},
                event: { event: '$pageview', properties: { $current_url: 'https://posthog.com' } } as any,
            })

        it('injects the invoked function as the globals source', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const globals = createHogExecutionGlobals({ groups: {} })
            expect(globals.source).toBeUndefined()

            const { invocations } = await buildHogFunctionInvocations(hogInputsService, [fn], globals)

            expect(invocations).toHaveLength(1)
            expect(invocations[0].state.globals.source).toEqual({
                name: 'Hog Function',
                url: `http://localhost:8000/projects/1/functions/${fn.id}/configuration/`,
            })
        })

        it('builds an invocation only when the filters match, counting a filtered metric otherwise', async () => {
            const fn = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
            })

            const notMatched = await buildHogFunctionInvocations(
                hogInputsService,
                [fn],
                createHogExecutionGlobals({ groups: {} })
            )
            expect(notMatched.invocations).toHaveLength(0)
            expect(notMatched.metrics.map((m) => m.metric_name)).toEqual(['filtered'])

            const matched = await buildHogFunctionInvocations(hogInputsService, [fn], pageviewGlobals())
            expect(matched.invocations).toHaveLength(1)
            expect(matched.metrics).toHaveLength(0)
        })

        // Filters that read elements_chain_* only match if the chain is parsed into the filter globals.
        // The parsing itself is covered in hog-function-filtering.test.ts; these rows check that a real
        // autocapture filter of each shape actually gates invocation building.
        const elementsChainCases = [
            {
                shape: 'text',
                filters: HOG_FILTERS_EXAMPLES.elements_text_filter,
                notMatching: 'Not our text',
                matching: 'Reload',
                chain: (buttonText: string) =>
                    `span.LemonButton__content:attr__class="LemonButton__content"nth-child="2"nth-of-type="2"text="${buttonText}";span.LemonButton__chrome:attr__class="LemonButton__chrome"nth-child="1"nth-of-type="1";button.LemonButton.LemonButton--has-icon.LemonButton--secondary.LemonButton--status-default:attr__class="LemonButton LemonButton--secondary LemonButton--status-default LemonButton--has-icon"attr__type="button"nth-child="1"nth-of-type="1"text="${buttonText}";div.flex.gap-4.items-center:attr__class="flex gap-4 items-center"nth-child="1"nth-of-type="1"`,
            },
            {
                shape: 'href',
                filters: HOG_FILTERS_EXAMPLES.elements_href_filter,
                notMatching: '/project/1/not-a-link',
                matching: '/project/1/activity/explore',
                chain: (link: string) =>
                    `span.LemonButton__content:attr__class="LemonButton__content"attr__href="${link}"href="${link}"nth-child="2"nth-of-type="2"text="Activity";a.LemonButton.Link.NavbarButton:attr__class="Link LemonButton NavbarButton"attr__href="${link}"href="${link}"nth-child="1"nth-of-type="1"text="Activity"`,
            },
            {
                shape: 'tag and id',
                filters: HOG_FILTERS_EXAMPLES.elements_tag_and_id_filter,
                notMatching: 'notfound',
                matching: 'homelink',
                chain: (id: string) =>
                    `a.Link.font-semibold:attr__class="Link font-semibold"attr__href="/project/1/dashboard/1"attr__id="${id}"attr_id="${id}"href="/project/1/dashboard/1"nth-child="1"nth-of-type="1"text="My App Dashboard"`,
            },
        ]

        it.each(elementsChainCases)(
            'gates invocation building on an elements-chain $shape filter',
            async ({ filters, chain, notMatching, matching }) => {
                const fn = createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...filters,
                })

                const autocaptureGlobals = (elementsChain: string) =>
                    createHogExecutionGlobals({
                        groups: {},
                        event: {
                            uuid: 'uuid',
                            event: '$autocapture',
                            elements_chain: elementsChain,
                            distinct_id: 'distinct_id',
                            url: 'http://localhost:8000/events/1',
                            properties: { $lib_version: '1.2.3' },
                            timestamp: '2025-01-01T00:00:00.000Z',
                        },
                    })

                const notMatched = await buildHogFunctionInvocations(
                    hogInputsService,
                    [fn],
                    autocaptureGlobals(chain(notMatching))
                )
                expect(notMatched.invocations).toHaveLength(0)
                expect(notMatched.metrics.map((m) => m.metric_name)).toEqual(['filtered'])

                const matched = await buildHogFunctionInvocations(
                    hogInputsService,
                    [fn],
                    autocaptureGlobals(chain(matching))
                )
                expect(matched.invocations).toHaveLength(1)
                expect(matched.metrics).toHaveLength(0)
            }
        )

        describe('mappings', () => {
            const mappingFunction = () =>
                createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                    mappings: [
                        {
                            // Filters for pageview or autocapture, and overrides the url input
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
                        // No filters so should match all events
                        { ...HOG_FILTERS_EXAMPLES.no_filters },
                        // Broken filters so shouldn't match
                        { ...HOG_FILTERS_EXAMPLES.broken_filters },
                    ],
                })

            it('builds one invocation per matching mapping', async () => {
                const results = await buildHogFunctionInvocations(
                    hogInputsService,
                    [mappingFunction()],
                    pageviewGlobals()
                )

                expect(results.invocations).toHaveLength(2)
                expect(results.metrics.map((m) => m.metric_name)).toEqual(['filtering_failed'])
                expect(results.logs.map((l) => l.message)).toMatchInlineSnapshot(`
                    [
                      "Error filtering event uuid: Invalid HogQL bytecode, stack is empty, can not pop",
                    ]
                `)
            })

            it('skips mappings whose filters do not match', async () => {
                const results = await buildHogFunctionInvocations(
                    hogInputsService,
                    [mappingFunction()],
                    createHogExecutionGlobals({ event: { event: 'test' } as any })
                )

                // Only the unfiltered mapping survives
                expect(results.invocations).toHaveLength(1)
                expect(results.metrics.map((m) => m.metric_name)).toEqual(['filtered', 'filtering_failed'])
            })

            it('resolves each matching mapping against its own inputs', async () => {
                const { invocations } = await buildHogFunctionInvocations(
                    hogInputsService,
                    [mappingFunction()],
                    pageviewGlobals()
                )

                // The first mapping overrides url; both inherit the top-level headers
                expect(invocations[0].state.globals.inputs.url).toBe('https://example.com?q=$pageview')
                expect(invocations[0].state.globals.inputs.headers).toEqual({ version: 'v=' })
                expect(invocations[1].state.globals.inputs.url).toBe('https://example.com/posthog-webhook')
                expect(invocations[1].state.globals.inputs.headers).toEqual({ version: 'v=' })
            })

            // `mappings: []` takes the mapping path and matches nothing, so the function never runs.
            // A destination saved with no mappings is silently a no-op rather than an unmapped send.
            it('builds nothing for a function with an empty mappings array', async () => {
                const fn = createHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                    mappings: [],
                })

                const results = await buildHogFunctionInvocations(hogInputsService, [fn], pageviewGlobals())

                expect(results.invocations).toHaveLength(0)
                expect(results.metrics).toHaveLength(0)
            })
        })

        it('reports a function whose inputs fail to build without dropping the rest of the batch', async () => {
            const broken = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
                inputs_schema: [{ key: 'url', type: 'string', label: 'Webhook URL', required: true }],
                // Truncated bytecode - resolving this input throws
                inputs: { url: { order: 0, value: 'https://example.com', bytecode: ['_H', 1, 2] } },
            })
            const healthy = createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            const results = await buildHogFunctionInvocations(hogInputsService, [broken, healthy], pageviewGlobals())

            expect(results.invocations.map((i) => i.functionId)).toEqual([healthy.id])
            expect(results.metrics).toMatchObject([
                { app_source_id: broken.id, metric_kind: 'failure', metric_name: 'inputs_failed', count: 1 },
            ])
            expect(results.logs).toMatchObject([
                {
                    level: 'error',
                    log_source: 'hog_function',
                    log_source_id: broken.id,
                    message: expect.stringContaining('Error building inputs for event uuid:'),
                },
            ])
        })
    })

    describe('cloneInvocation', () => {
        beforeEach(() => {
            const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
            jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        const invocation = createInvocation(
            {
                ...createHogExecutionGlobals(),
                inputs: { foo: 'bar' },
            },
            createHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.elements_href_filter,
            })
        )

        invocation.queueSource = 'postgres'

        it('should clone an invocation', () => {
            const cloned = cloneInvocation(invocation)
            const { id, state, hogFunction, functionId, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(functionId).toBe(invocation.functionId)
            expect(state).toBe(invocation.state)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": undefined,
                  "queueParameters": undefined,
                  "queuePriority": 0,
                  "queueScheduledAt": undefined,
                  "queueSource": "postgres",
                  "teamId": 1,
                }
            `)
        })

        it('should allow overriding properties', () => {
            const cloned = cloneInvocation(invocation, {
                queuePriority: 1,
                queueMetadata: { foo: 'bar' },
                queueScheduledAt: DateTime.utc(),
                queueParameters: {
                    type: 'fetch',
                    url: 'https://example.com',
                    method: 'GET',
                },
            })

            const { id, state, hogFunction, functionId, ...rest } = cloned
            expect(id).toBe(invocation.id)
            expect(functionId).toBe(invocation.functionId)
            expect(state).toBe(invocation.state)
            expect(hogFunction).toBe(invocation.hogFunction)

            expect(rest).toMatchInlineSnapshot(`
                {
                  "queue": "hog",
                  "queueMetadata": {
                    "foo": "bar",
                  },
                  "queueParameters": {
                    "method": "GET",
                    "type": "fetch",
                    "url": "https://example.com",
                  },
                  "queuePriority": 1,
                  "queueScheduledAt": "2025-01-01T00:00:00.000Z",
                  "queueSource": "postgres",
                  "teamId": 1,
                }
            `)
        })
    })
})
