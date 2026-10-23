import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'
import { teamLogic } from 'scenes/teamLogic'

import { FlagEvaluationsModeEnumApi } from '~/generated/core/api.schemas'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    CyclotronJobFilterEvents,
    CyclotronJobFiltersType,
    HogFunctionTemplateType,
    HogFunctionType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { FLAG_CALLS_NOT_LOADABLE } from '../filters/flagCallsMatching'
import { performWideEventsQueryInTwoPhases } from '../sampleEventsQuery'
import { hogFunctionConfigurationLogic, sanitizeInputs } from './hogFunctionConfigurationLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        getTemplate: jest.fn(),
        update: jest.fn(),
        create: jest.fn(),
    },
}))

jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))

jest.mock('../sampleEventsQuery', () => ({
    ...jest.requireActual('../sampleEventsQuery'),
    performWideEventsQueryInTwoPhases: jest.fn(),
}))

// the mock api object

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>

const HOG_TEMPLATE: HogFunctionTemplateType = {
    free: false,
    status: 'beta',
    id: 'template-webhook',
    type: 'destination',
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    code: "let res := fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.body,\n  'method': inputs.method\n});\n\nif (inputs.debug) {\n  print('Response', res.status, res.body);\n}",
    code_language: 'hog',
    inputs_schema: [
        {
            key: 'url',
            type: 'string',
            label: 'Webhook URL',
            secret: false,
            required: true,
        },
        {
            key: 'method',
            type: 'choice',
            label: 'Method',
            secret: false,
            choices: [
                {
                    label: 'POST',
                    value: 'POST',
                },
                {
                    label: 'PUT',
                    value: 'PUT',
                },
                {
                    label: 'PATCH',
                    value: 'PATCH',
                },
                {
                    label: 'GET',
                    value: 'GET',
                },
                {
                    label: 'DELETE',
                    value: 'DELETE',
                },
            ],
            default: 'POST',
            required: false,
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON Body',
            default: {
                event: '{event}',
                person: '{person}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the response of http calls for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
    filters: null,
    masking: null,
    icon_url: '/static/posthog-icon.svg',
}

const HOG_FUNCTION: HogFunctionType = {
    ...HOG_TEMPLATE,
    hog: HOG_TEMPLATE.code,
    description: typeof HOG_TEMPLATE.description === 'string' ? HOG_TEMPLATE.description : '',
    created_at: '2021-09-29T14:00:00Z',
    created_by: {} as any,
    id: '123-456-789',
    updated_at: '2021-09-29T14:00:00Z',
    enabled: true,
    status: undefined,
}

describe('hogFunctionConfigurationLogic', () => {
    let logic: ReturnType<typeof hogFunctionConfigurationLogic.build>

    describe('template', () => {
        beforeEach(() => {
            initKeaTests()

            mockApi.getTemplate.mockReturnValue(Promise.resolve(HOG_TEMPLATE))
            mockApi.create.mockReturnValue(Promise.resolve(HOG_FUNCTION))
            mockApi.update.mockReturnValue(Promise.resolve(HOG_FUNCTION))

            logic = hogFunctionConfigurationLogic({
                templateId: 'test',
            })
        })

        it('has expected defaults', async () => {
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplate', 'loadTemplateSuccess'])

            expect(logic.values.template).toEqual(HOG_TEMPLATE)
            expect(logic.values.configuration).toEqual({
                name: HOG_TEMPLATE.name,
                type: HOG_TEMPLATE.type,
                description: HOG_TEMPLATE.description,
                inputs_schema: HOG_TEMPLATE.inputs_schema,
                filters: null,
                hog: HOG_TEMPLATE.code,
                icon_url: HOG_TEMPLATE.icon_url,
                inputs: {
                    method: { value: 'POST' },
                    body: {
                        value: {
                            event: '{event}',
                            person: '{person}',
                        },
                    },
                    debug: {
                        value: false,
                    },
                },
                enabled: true,
            })
        })

        it('sets rejects submission if missing inputs', async () => {
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplate', 'loadTemplateSuccess'])

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfigurationFailure'])

            expect(logic.values.configurationErrors).toMatchObject({
                inputs: {
                    url: 'This field is required',
                },
            })
        })

        it('saves if form valid', async () => {
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadTemplate', 'loadTemplateSuccess'])
            logic.actions.setConfigurationValue('inputs.url', { value: 'https://posthog.com' })

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['upsertHogFunction', 'submitConfigurationSuccess'])
        })
    })

    describe('sanitizeInputs', () => {
        it('does not send a placeholder value for an untouched secret', () => {
            // A value here can be encrypted over the stored secret, so an untouched secret must
            // carry only { secret: true }.
            const result = sanitizeInputs({
                inputs_schema: [{ key: 'api_key', label: 'API key', type: 'string', secret: true }],
                inputs: { api_key: { value: '********', secret: true } },
            })

            expect(result.api_key.value).toBeUndefined()
            expect(result.api_key.secret).toBe(true)
        })
    })

    describe('log transformation', () => {
        const LOG_TEMPLATE: HogFunctionTemplateType = {
            free: true,
            status: 'stable',
            id: 'template-log-transformation-default',
            type: 'transformation_log',
            name: 'Custom log transformation',
            description: 'Start from scratch.',
            code: 'return record',
            code_language: 'hog',
            inputs_schema: [],
            filters: null,
            masking: null,
            icon_url: '/static/hedgehog/builder-hog-01.png',
        }

        beforeEach(() => {
            initKeaTests()
            mockApi.getTemplate.mockReturnValue(Promise.resolve(LOG_TEMPLATE))
            logic = hogFunctionConfigurationLogic({ templateId: 'test' })
            logic.mount()
        })

        it('seeds the inline tester with a sample record, not an event', async () => {
            await expectLogic(logic).toDispatchActions(['loadTemplate', 'loadTemplateSuccess'])
            const globals = logic.values.exampleInvocationGlobals
            expect(globals.record).toBeTruthy()
            expect(globals.record?.body).toContain('GET /api/users')
            expect(globals.event).toBeUndefined()
        })

        it('surfaces validation errors on `type` as a toast, since no form field renders them', async () => {
            // The feature-flag gate and the enabled-function cap both reject with attr `type`;
            // without the toast the Save button fails with no visible feedback at all.
            const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')
            const detail = 'Log transformations are not enabled for this team.'
            mockApi.create.mockRejectedValue({
                status: 400,
                data: { type: 'validation_error', code: 'invalid_input', attr: 'type', detail },
            })
            await expectLogic(logic).toDispatchActions(['loadTemplate', 'loadTemplateSuccess'])

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['upsertHogFunctionFailure'])

            expect(toastSpy).toHaveBeenCalledWith(detail)
        })
    })

    describe('resetting to template', () => {
        const USER_FILTERS: CyclotronJobFiltersType = {
            events: [{ id: '$pageview', name: '$pageview', type: 'events', order: 0 }],
            filter_test_accounts: false,
        }
        const TEMPLATE_DEFAULT_FILTERS: CyclotronJobFiltersType = {
            events: [],
            actions: [],
            filter_test_accounts: true,
        }
        const TEMPLATE_WITH_DEFAULT_FILTERS: HogFunctionTemplateType = {
            ...HOG_TEMPLATE,
            code: `${HOG_TEMPLATE.code}\n// updated`,
            filters: TEMPLATE_DEFAULT_FILTERS,
        }

        beforeEach(() => {
            initKeaTests()
            mockApi.getTemplate.mockResolvedValue(TEMPLATE_WITH_DEFAULT_FILTERS)
        })

        it.each([
            ['keeps the configured filters over the template defaults', USER_FILTERS, USER_FILTERS],
            ['falls back to the template defaults when none are configured', null, TEMPLATE_DEFAULT_FILTERS],
        ])('%s', async (_name, functionFilters, expectedFilters) => {
            mockApi.get.mockResolvedValue({
                ...HOG_FUNCTION,
                filters: functionFilters,
                template: TEMPLATE_WITH_DEFAULT_FILTERS,
            })
            logic = hogFunctionConfigurationLogic({ id: HOG_FUNCTION.id })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadHogFunctionSuccess'])

            await expectLogic(logic, () => {
                logic.actions.resetToTemplate()
            }).toDispatchActions(['setConfigurationValues'])

            expect(logic.values.configuration.filters).toEqual(expectedFilters)
            expect(logic.values.configuration.hog).toEqual(TEMPLATE_WITH_DEFAULT_FILTERS.code)
        })
    })

    describe('loading a missing function', () => {
        beforeEach(() => {
            initKeaTests()
        })

        it('resolves to null on a 404 so the not-found state renders without filing an exception', async () => {
            // A cross-project deep link 404s here; the loader must swallow it rather than reject,
            // which would surface as an unhandled rejection in error tracking.
            mockApi.get.mockRejectedValue(new ApiError('Not found', 404))
            logic = hogFunctionConfigurationLogic({ id: 'missing-id' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadHogFunction', 'loadHogFunctionSuccess'])
            expect(logic.values.hogFunction).toBeNull()
            expect(logic.values.loaded).toBe(false)
        })

        it('still rejects on non-404 errors', async () => {
            mockApi.get.mockRejectedValue(new ApiError('Boom', 500))
            logic = hogFunctionConfigurationLogic({ id: 'boom-id' })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadHogFunction', 'loadHogFunctionFailure'])
        })
    })

    describe('internal destination without a trigger', () => {
        const INTERNAL_DESTINATION: HogFunctionType = {
            ...HOG_FUNCTION,
            type: 'internal_destination',
            filters: {},
        }

        beforeEach(() => {
            initKeaTests()
            mockApi.get.mockReturnValue(Promise.resolve(INTERNAL_DESTINATION))
            mockApi.update.mockReturnValue(Promise.resolve(INTERNAL_DESTINATION))
            logic = hogFunctionConfigurationLogic({ id: INTERNAL_DESTINATION.id })
            logic.mount()
        })

        it('blocks the save client-side, since the backend requires an explicit event', async () => {
            // A legacy internal destination stores no events at all, so the rule has to catch an
            // absent list and not just an empty one — otherwise the form posts a payload the
            // backend rejects, and the user gets no feedback.
            await expectLogic(logic).toDispatchActions(['loadHogFunction', 'loadHogFunctionSuccess'])

            await expectLogic(logic, () => {
                logic.actions.submitConfiguration()
            }).toDispatchActions(['submitConfigurationFailure'])

            expect(logic.values.configurationErrors.filters).toBe('You must choose a filter')
            expect(mockApi.update).not.toHaveBeenCalled()
        })
    })

    describe('a destination on feature flag calls', () => {
        const FLAG_CALLED: CyclotronJobFilterEvents = {
            id: '$feature_flag_called',
            name: '$feature_flag_called',
            type: 'events',
            order: 0,
            properties: [
                {
                    key: '$feature_flag',
                    value: 'my-flag',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        }
        const PAGEVIEW: CyclotronJobFilterEvents = { id: '$pageview', name: '$pageview', type: 'events', order: 1 }
        const NO_MATCH_IN_30_DAYS =
            'No events match these filters in the last 30 days. Showing an example $pageview event instead.'

        function mountOnMode(
            mode: FlagEvaluationsModeEnumApi,
            events: CyclotronJobFilterEvents[] = [FLAG_CALLED]
        ): void {
            mockApi.getTemplate.mockReturnValue(Promise.resolve({ ...HOG_TEMPLATE, filters: { events } }))
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, flag_evaluations_mode: mode })
            logic = hogFunctionConfigurationLogic({ templateId: 'test' })
            logic.mount()
        }

        beforeEach(() => {
            initKeaTests()
            ;(performQuery as jest.Mock).mockReset()
            ;(performQuery as jest.Mock).mockImplementation(async (query) =>
                query.kind === NodeKind.EventsQuery
                    ? {
                          results: [
                              ['2026-10-16', 700],
                              ['2026-10-17', 3],
                          ],
                      }
                    : {
                          results: [
                              {
                                  data: [0, 500, 0],
                                  count: 500,
                                  labels: ['15-Oct-2026', '16-Oct-2026', '17-Oct-2026'],
                                  days: ['2026-10-15', '2026-10-16', '2026-10-17'],
                              },
                          ],
                      }
            )
            ;(performWideEventsQueryInTwoPhases as jest.Mock).mockReset()
            ;(performWideEventsQueryInTwoPhases as jest.Mock).mockResolvedValue({ results: [] })
        })

        // Mode 1 still writes flag calls to events, so only mode 2 adds the flag_evaluations count.
        it.each([
            ['events', FlagEvaluationsModeEnumApi.Number0, 500, [0, 0, 0], undefined],
            ['read flag evaluations', FlagEvaluationsModeEnumApi.Number1, 500, [0, 0, 0], undefined],
            [
                'flag evaluations only',
                FlagEvaluationsModeEnumApi.Number2,
                1203,
                [0, 200, 0],
                'person_id_no_override_properties_on_events',
            ],
        ])(
            'estimates the calls it would receive on the %s mode',
            async (_name, mode, count, highVolume, flagCallsPersonsMode) => {
                mountOnMode(mode)
                await expectLogic(logic).toDispatchActions(['loadTemplateSuccess', 'sparklineQueryChangedSuccess'])

                expect(logic.values.sparkline?.count).toEqual(count)
                expect(logic.values.sparkline?.data.find(({ name }) => name === 'High volume')?.values).toEqual(
                    highVolume
                )
                const flagCallsQuery = (performQuery as jest.Mock).mock.calls
                    .map(([query]) => query)
                    .find((query) => query.kind === NodeKind.EventsQuery)
                expect(flagCallsQuery?.modifiers?.personsOnEventsMode).toBe(flagCallsPersonsMode)
            }
        )

        it.each([
            [
                'events mode',
                FlagEvaluationsModeEnumApi.Number0,
                [FLAG_CALLED],
                NO_MATCH_IN_30_DAYS,
                '$pageview',
                undefined,
            ],
            // The example flag call names the flag that the destination filters on, so a test run passes the filters.
            [
                'flag evaluations only mode',
                FlagEvaluationsModeEnumApi.Number2,
                [FLAG_CALLED],
                `${FLAG_CALLS_NOT_LOADABLE} Showing an example $feature_flag_called event instead.`,
                '$feature_flag_called',
                'my-flag',
            ],
            // A pageview can still match, so the notice about flag calls does not apply.
            [
                'flag evaluations only mode with a pageview matcher',
                FlagEvaluationsModeEnumApi.Number2,
                [FLAG_CALLED, PAGEVIEW],
                NO_MATCH_IN_30_DAYS,
                '$pageview',
                undefined,
            ],
        ])('explains a missing test event on the %s', async (_name, mode, events, message, exampleEvent, flagKey) => {
            mountOnMode(mode, events)
            await expectLogic(logic).toDispatchActions(['loadTemplateSuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSampleGlobals()
            }).toDispatchActions(['loadSampleGlobalsSuccess'])

            expect(logic.values.sampleGlobalsError).toEqual(message)
            expect(logic.values.sampleGlobals?.event.event).toEqual(exampleEvent)
            expect(logic.values.sampleGlobals?.event.properties.$feature_flag).toEqual(flagKey)
        })
    })
})
