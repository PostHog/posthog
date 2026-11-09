import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { hogFunctionsPublishCreate } from 'products/cdp/frontend/generated/api'

import { hogFunctionConfigurationLogic } from './hogFunctionConfigurationLogic'
import { hogFunctionDraftLogic } from './hogFunctionDraftLogic'
import { hogFunctionSecretReentryLogic } from './hogFunctionSecretReentryLogic'
import { parseSecretReentryRefusal } from './inputRefusal'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        update: jest.fn(),
        createTestInvocation: jest.fn(),
    },
}))

jest.mock('products/cdp/frontend/generated/api', () => ({
    ...jest.requireActual('products/cdp/frontend/generated/api'),
    hogFunctionsPublishCreate: jest.fn(),
}))

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>
const mockPublish = hogFunctionsPublishCreate as jest.MockedFunction<typeof hogFunctionsPublishCreate>

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
        { key: 'signing_cert', type: 'json', label: 'Signing certificate', secret: true, required: false },
        { key: 'slack', type: 'integration', integration: 'slack', label: 'Slack', secret: false, required: false },
    ],
    inputs: {
        url: { value: 'https://hooks.example.com' },
        api_key: { value: undefined, secret: true },
        secret_headers: { secret: true, value: { Authorization: '********' } },
        signing_cert: { value: undefined, secret: true },
        slack: { value: 1 },
    },
}

const refusalDetail = (key: string): string =>
    `This change sends ${key} to new.example.com. Until now it was only sent to hooks.example.com. Enter it again to confirm.`

const refusal = (key: string): ApiError =>
    new ApiError('Bad request', 400, undefined, {
        type: 'validation_error',
        code: 'secret_reentry_required',
        attr: `inputs__${key}`,
        detail: refusalDetail(key),
    })

const CONNECTION_DETAIL =
    'Slack connections can only send credentials to slack.com. Remove the change that sends them anywhere else.'

const connectionRefusal = new ApiError('Bad request', 400, undefined, {
    type: 'validation_error',
    code: 'integration_origin_refused',
    attr: 'inputs__slack',
    detail: CONNECTION_DETAIL,
})

describe('hogFunctionSecretReentryLogic', () => {
    let configLogic: ReturnType<typeof hogFunctionConfigurationLogic.build>
    let logic: ReturnType<typeof hogFunctionSecretReentryLogic.build>

    // Imported after initKeaTests, because the test logic, which the scene also imports, reads the team id from the
    // app context at import.
    const mountTestLogic = async (): Promise<
        ReturnType<typeof import('./hogFunctionTestLogic').hogFunctionTestLogic.build>
    > => {
        const { hogFunctionTestLogic } = await import('./hogFunctionTestLogic')
        const testLogic = hogFunctionTestLogic({ id: SECRET_SENDER.id })
        testLogic.mount()
        return testLogic
    }

    beforeEach(async () => {
        jest.restoreAllMocks()
        initKeaTests()
        mockApi.get.mockResolvedValue(SECRET_SENDER)
        mockApi.update.mockReset()
        mockApi.createTestInvocation.mockReset()
        mockPublish.mockReset()
        configLogic = hogFunctionConfigurationLogic({ id: SECRET_SENDER.id })
        configLogic.mount()
        logic = hogFunctionSecretReentryLogic({ id: SECRET_SENDER.id })
        logic.mount()
        await expectLogic(configLogic).toDispatchActions(['loadHogFunctionSuccess'])
        configLogic.actions.setConfigurationValue('inputs.url', { value: 'https://new.example.com' })
    })

    afterEach(() => {
        cleanup()
    })

    it('asks for each refused secret in turn and retries the save with the edits kept', async () => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')
        mockApi.update
            .mockRejectedValueOnce(refusal('api_key'))
            .mockRejectedValueOnce(refusal('secret_headers'))
            .mockResolvedValueOnce(SECRET_SENDER)

        await expectLogic(logic, () => configLogic.actions.submitConfiguration()).toDispatchActions([
            'openSecretReentry',
        ])
        expect(logic.values.prompt).toEqual({
            key: 'api_key',
            label: 'API key',
            detail: refusalDetail('api_key'),
            entryKeys: null,
            source: 'save',
        })

        logic.actions.setSecretValue('new key')
        await expectLogic(logic, () => logic.actions.confirmSecretReentry()).toDispatchActions(['openSecretReentry'])
        // The server names one refused input per response, so each dialog shows the hosts for its own input.
        expect(logic.values.prompt).toEqual({
            key: 'secret_headers',
            label: 'Secret headers',
            detail: refusalDetail('secret_headers'),
            entryKeys: ['Authorization'],
            source: 'save',
        })

        logic.actions.setSecretEntry('Authorization', 'Bearer new')
        await expectLogic(configLogic, () => logic.actions.confirmSecretReentry()).toDispatchActions([
            'upsertHogFunctionSuccess',
        ])

        expect(logic.values.isOpen).toBe(false)
        // The dialog is the only feedback: no generic "failed" toast shows over it.
        expect(toastSpy).not.toHaveBeenCalled()
        expect(mockApi.update).toHaveBeenCalledTimes(3)
        expect(mockApi.update.mock.calls[2][1].inputs).toMatchObject({
            url: { value: 'https://new.example.com' },
            api_key: { value: 'new key' },
            secret_headers: { value: { Authorization: 'Bearer new' } },
        })
    })

    it('opens the dialog from the scene for a refused save, with no failure toast over it', async () => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')
        mockApi.update.mockRejectedValueOnce(refusal('api_key'))
        const { HogFunctionScene, hogFunctionSceneLogic } = await import('../HogFunctionScene')
        const props = { id: SECRET_SENDER.id }
        // The History tab keeps the render light: the dialog sits above the tabs, so any tab shows it.
        hogFunctionSceneLogic(props).actions.setCurrentTab('history')
        render(
            <BindLogic logic={hogFunctionSceneLogic} props={props}>
                <HogFunctionScene />
            </BindLogic>
        )

        configLogic.actions.submitConfiguration()

        // The modal shows the refusal detail as its description, so finding the text proves the scene mounts it.
        await screen.findByText(refusalDetail('api_key'))
        expect(toastSpy).not.toHaveBeenCalled()
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
        expect(logic.values.prompt).toMatchObject({ key: 'api_key', detail: refusalDetail('api_key'), source: 'test' })

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

    it('asks for a secret the staged draft moves and publishes it with the entered value', async () => {
        configLogic.actions.loadHogFunctionSuccess({
            ...SECRET_SENDER,
            draft: {
                inputs_schema: SECRET_SENDER.inputs_schema,
                inputs: { api_key: { value: undefined, secret: true } },
            },
        })
        const draftLogic = hogFunctionDraftLogic({ id: SECRET_SENDER.id })
        draftLogic.mount()
        mockPublish.mockRejectedValueOnce(refusal('api_key')).mockResolvedValueOnce({
            published: true,
            draft_updated_at: null,
            confirm_token: null,
            changed_fields: null,
            function: SECRET_SENDER as any,
        })

        await expectLogic(logic, () => draftLogic.actions.confirmPublishDraft('preview-token')).toDispatchActions([
            'openSecretReentry',
        ])
        expect(logic.values.prompt).toMatchObject({
            key: 'api_key',
            detail: refusalDetail('api_key'),
            source: 'publish',
        })
        expect(draftLogic.values.draftActionPending).toBeNull()

        logic.actions.setSecretValue('new key')
        await expectLogic(configLogic, () => logic.actions.confirmSecretReentry()).toDispatchActions([
            'loadHogFunctionSuccess',
        ])

        expect(mockPublish).toHaveBeenCalledTimes(2)
        expect(mockPublish.mock.calls[1][2]).toEqual({
            confirm: true,
            confirm_token: 'preview-token',
            inputs: { api_key: { value: 'new key' } },
        })
        // The form holds the live config, so the secret entered for the draft never lands in it.
        expect(configLogic.values.configuration.inputs?.api_key).toEqual({ secret: true })
    })

    // A form that shows an error does not submit, so the other field's error arrives while the request is in flight.
    const OTHER_FIELD_ERRORS = { name: 'Name taken', inputs: { url: 'Enter a valid URL' } }

    const refuseSave = async (error: ApiError): Promise<void> => {
        mockApi.update.mockImplementationOnce(async () => {
            configLogic.actions.setConfigurationManualErrors(OTHER_FIELD_ERRORS)
            throw error
        })
        configLogic.actions.submitConfiguration()
    }

    const refuseTestRun = async (error: ApiError): Promise<void> => {
        const testLogic = await mountTestLogic()
        mockApi.createTestInvocation.mockImplementationOnce(async () => {
            configLogic.actions.setConfigurationManualErrors(OTHER_FIELD_ERRORS)
            throw error
        })
        testLogic.actions.submitTestInvocation()
    }

    const refusePublish = async (error: ApiError): Promise<void> => {
        configLogic.actions.loadHogFunctionSuccess({ ...SECRET_SENDER, draft: { hog: SECRET_SENDER.hog } })
        const draftLogic = hogFunctionDraftLogic({ id: SECRET_SENDER.id })
        draftLogic.mount()
        mockPublish.mockImplementationOnce(async () => {
            configLogic.actions.setConfigurationManualErrors(OTHER_FIELD_ERRORS)
            throw error
        })
        draftLogic.actions.confirmPublishDraft('preview-token')
    }

    it.each([
        ['a save', refuseSave],
        ['a test run', refuseTestRun],
        ['a publish', refusePublish],
    ])('marks the connection input when %s refuses it, with no toast and no dialog', async (_source, refuse) => {
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')

        await refuse(connectionRefusal)
        // A save sets its field error 1ms after the failure, so wait past that.
        await expectLogic(configLogic).delay(10)

        expect(configLogic.values.configurationManualErrors.inputs).toMatchObject({ slack: CONNECTION_DETAIL })
        expect(toastSpy).not.toHaveBeenCalled()
        expect(logic.values.isOpen).toBe(false)
    })

    it.each([
        ['a save', 'not_in_schema', refuseSave, 'Enter not_in_schema again in the form.', false],
        ['a save', 'signing_cert', refuseSave, 'Enter Signing certificate again in the form.', true],
        ['a test run', 'signing_cert', refuseTestRun, 'Enter Signing certificate again in the form.', true],
    ])(
        'falls back to a toast naming the input when %s refuses %s, which the dialog cannot ask for',
        async (_source, key, refuse, toastStart, marksField) => {
            const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'id')

            await expectLogic(logic, () => refuse(refusal(key))).toDispatchActions(['requireSecretReentry'])

            expect(logic.values.isOpen).toBe(false)
            expect(toastSpy).toHaveBeenCalledTimes(1)
            expect(toastSpy.mock.calls[0][0]).toMatch(new RegExp(`^${toastStart}`))
            expect(configLogic.values.configurationManualErrors).toEqual(
                marksField
                    ? { ...OTHER_FIELD_ERRORS, inputs: { ...OTHER_FIELD_ERRORS.inputs, [key]: refusalDetail(key) } }
                    : OTHER_FIELD_ERRORS
            )
        }
    )

    it.each([
        ['a refusal', refusal('api_key'), { key: 'api_key', detail: refusalDetail('api_key') }],
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
