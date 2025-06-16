import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { HogFunctionTemplateType, HogFunctionType } from '~/types'

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

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'

const HOG_TEMPLATE: HogFunctionTemplateType = {
    free: false,
    status: 'beta',
    id: 'template-webhook',
    type: 'destination',
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    hog: "let res := fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.body,\n  'method': inputs.method\n});\n\nif (inputs.debug) {\n  print('Response', res.status, res.body);\n}",
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
                hog: HOG_TEMPLATE.hog,
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
})
