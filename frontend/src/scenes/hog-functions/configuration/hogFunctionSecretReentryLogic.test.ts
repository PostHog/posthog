import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { hogFunctionSecretReentryLogic } from './hogFunctionSecretReentryLogic'
import { parseSecretReentryRefusal } from './secretReentryRefusal'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        update: jest.fn(),
        createTestInvocation: jest.fn(),
    },
}))

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>

const SECRET_SENDER: HogFunctionType = {
    id: '123-456-789',
    type: 'destination',
    name: 'HTTP Webhook',
    description: '',
    enabled: true,
    hog: "fetch(inputs.url, {'headers': inputs.secret_headers, 'body': inputs.api_key})",
    created_at: '2021-09-29T14:00:00Z',
    created_by: {} as any,
    updated_at: '2021-09-29T14:00:00Z',
    filters: null,
    masking: null,
    icon_url: '/static/posthog-icon.svg',
    inputs_schema: [
        { key: 'url', type: 'string', label: 'Webhook URL', secret: false, required: true },
        { key: 'api_key', type: 'string', label: 'API key', secret: true, required: false },
        { key: 'secret_headers', type: 'dictionary', label: 'Secret headers', secret: true, required: false },
    ],
    inputs: {
        url: { value: 'https://hooks.example.com' },
        api_key: { value: undefined, secret: true },
        secret_headers: { secret: true, value: { Authorization: '********' } },
    },
}

const REFUSAL_DETAIL = 'This change would send the secret to a new address. Enter the secret again to confirm.'

const refusal = (key: string): Record<string, unknown> => ({
    status: 400,
    data: { type: 'validation_error', code: 'secret_reentry_required', attr: `inputs__${key}`, detail: REFUSAL_DETAIL },
})

describe('hogFunctionSecretReentryLogic', () => {
    let configLogic: ReturnType<typeof hogFunctionConfigurationLogic.build>
    let logic: ReturnType<typeof hogFunctionSecretReentryLogic.build>

    // Imported after initKeaTests, because the test logic reads the team id from the app context at import.
    const mountTestLogic = async (): Promise<
        ReturnType<typeof import('./hogFunctionTestLogic').hogFunctionTestLogic.build>
    > => {
        const { hogFunctionTestLogic } = await import('./hogFunctionTestLogic')
        const testLogic = hogFunctionTestLogic({ id: SECRET_SENDER.id })
        testLogic.mount()
        return testLogic
    }

    beforeEach(async () => {
        initKeaTests()
        mockApi.get.mockResolvedValue(SECRET_SENDER)
        mockApi.update.mockReset()
        mockApi.createTestInvocation.mockReset()
        configLogic = hogFunctionConfigurationLogic({ id: SECRET_SENDER.id })
        configLogic.mount()
        logic = hogFunctionSecretReentryLogic({ id: SECRET_SENDER.id })
        logic.mount()
        await expectLogic(configLogic).toDispatchActions(['loadHogFunctionSuccess'])
        configLogic.actions.setConfigurationValue('inputs.url', { value: 'https://new.example.com' })
    })

    it('asks for each refused secret in turn and retries the save with the edits kept', async () => {
        mockApi.update
            .mockRejectedValueOnce(refusal('api_key'))
            .mockRejectedValueOnce(refusal('secret_headers'))
            .mockResolvedValueOnce(SECRET_SENDER)

        await expectLogic(logic, () => configLogic.actions.submitConfiguration()).toDispatchActions([
            'openSecretReentry',
        ])
        expect(logic.values.prompt).toEqual({ key: 'api_key', label: 'API key', entryKeys: null, source: 'save' })

        logic.actions.setSecretValue('new key')
        await expectLogic(logic, () => logic.actions.confirmSecretReentry()).toDispatchActions(['openSecretReentry'])
        expect(logic.values.prompt).toEqual({
            key: 'secret_headers',
            label: 'Secret headers',
            entryKeys: ['Authorization'],
            source: 'save',
        })

        logic.actions.setSecretEntry('Authorization', 'Bearer new')
        await expectLogic(configLogic, () => logic.actions.confirmSecretReentry()).toDispatchActions([
            'upsertHogFunctionSuccess',
        ])

        expect(logic.values.isOpen).toBe(false)
        expect(mockApi.update).toHaveBeenCalledTimes(3)
        expect(mockApi.update.mock.calls[2][1].inputs).toMatchObject({
            url: { value: 'https://new.example.com' },
            api_key: { value: 'new key' },
            secret_headers: { value: { Authorization: 'Bearer new' } },
        })
    })

    it('leaves the edit unsaved and the field without an error when the user cancels', async () => {
        mockApi.update.mockRejectedValueOnce(refusal('api_key'))

        await expectLogic(logic, () => configLogic.actions.submitConfiguration()).toDispatchActions([
            'openSecretReentry',
        ])
        logic.actions.setSecretValue('typed but not sent')
        logic.actions.cancelSecretReentry()

        expect(logic.values.isOpen).toBe(false)
        // The closing dialog keeps its content until it has animated out.
        expect(logic.values.prompt?.key).toEqual('api_key')
        logic.actions.clearSecretReentry()
        expect(logic.values.prompt).toBeNull()
        expect(logic.values.secretValue).toEqual('')

        // The form sets a field error 1ms after a failed save, so wait past that before checking none came.
        await expectLogic(configLogic).delay(10).toNotHaveDispatchedActions(['setConfigurationManualErrors'])
        expect(mockApi.update).toHaveBeenCalledTimes(1)
        expect(configLogic.values.configuration.inputs?.url).toEqual({ value: 'https://new.example.com' })
        expect(configLogic.values.configuration.inputs?.api_key).toEqual({ secret: true })
    })

    it('retries a refused test run with the entered secret', async () => {
        const testLogic = await mountTestLogic()
        mockApi.createTestInvocation
            .mockRejectedValueOnce(refusal('api_key'))
            .mockResolvedValueOnce({ status: 'success', logs: [] } as any)

        await expectLogic(logic, () => testLogic.actions.submitTestInvocation()).toDispatchActions([
            'openSecretReentry',
        ])
        expect(logic.values.prompt).toEqual({ key: 'api_key', label: 'API key', entryKeys: null, source: 'test' })

        logic.actions.setSecretValue('new key')
        await expectLogic(testLogic, () => logic.actions.confirmSecretReentry()).toDispatchActions([
            'submitTestInvocation',
            'setTestResult',
        ])

        expect(mockApi.createTestInvocation).toHaveBeenCalledTimes(2)
        expect(mockApi.createTestInvocation.mock.calls[1][1].configuration.inputs.api_key).toMatchObject({
            value: 'new key',
        })
    })

    it.each([
        [
            'save',
            async () => {
                mockApi.update.mockRejectedValueOnce(refusal('not_in_schema'))
                configLogic.actions.submitConfiguration()
            },
        ],
        [
            'test run',
            async () => {
                const testLogic = await mountTestLogic()
                mockApi.createTestInvocation.mockRejectedValueOnce(refusal('not_in_schema'))
                testLogic.actions.submitTestInvocation()
            },
        ],
    ])('shows the refusal as a toast when a %s refuses a secret the form cannot ask for', async (_, submit) => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')

        await expectLogic(logic, submit).toDispatchActions(['requireSecretReentry'])

        expect(logic.values.isOpen).toBe(false)
        expect(toastSpy).toHaveBeenCalledWith(REFUSAL_DETAIL)
    })

    it.each([
        ['a refusal', refusal('api_key'), { key: 'api_key', detail: REFUSAL_DETAIL }],
        ['another validation error', { data: { code: 'invalid_input', attr: 'inputs__api_key', detail: 'x' } }, null],
        ['a refusal without an attr', { data: { code: 'secret_reentry_required', detail: 'x' } }, null],
        [
            'a refusal on a mapping',
            { data: { code: 'secret_reentry_required', attr: 'mappings__0', detail: 'x' } },
            null,
        ],
        ['a network error', new Error('offline'), null],
    ])('reads the refused input from %s', (_, error, expected) => {
        expect(parseSecretReentryRefusal(error)).toEqual(expected)
    })
})
