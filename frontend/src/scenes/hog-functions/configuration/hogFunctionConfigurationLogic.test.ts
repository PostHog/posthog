import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { CyclotronJobFiltersType, HogFunctionTemplateType, HogFunctionType } from '~/types'

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
})
