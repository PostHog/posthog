import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { ALERT_NOTIFICATION_TYPE_SLACK, ALERT_NOTIFICATION_TYPE_WEBHOOK } from 'lib/utils/alertUtils'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { alertNotificationLogic } from './alertNotificationLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        // used by deleteWithUndo for the soft-delete PATCH
        update: jest.fn().mockResolvedValue({}),
        hogFunctions: {
            list: jest.fn(),
            update: jest.fn(),
            create: jest.fn(),
        },
    },
}))

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

const mockApi = api as jest.Mocked<typeof api>

const SLACK_HOG_FUNCTION = {
    id: 'hf-slack',
    name: 'Alert: Slack #old-channel',
    enabled: true,
    inputs: {
        channel: { value: 'C_OLD' },
        slack_workspace: { value: 1 },
        // an unrelated input we want to preserve through the update
        message: { value: 'hello' },
    },
    filters: {},
} as unknown as HogFunctionType

const WEBHOOK_HOG_FUNCTION = {
    id: 'hf-webhook',
    name: 'Alert: Webhook https://old.example/hook',
    enabled: true,
    inputs: {
        url: { value: 'https://old.example/hook' },
        body: { value: { foo: 'bar' } },
    },
    filters: {},
} as unknown as HogFunctionType

describe('alertNotificationLogic — edit flow', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it('pre-fills the slack picker when editing a slack destination', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        }).toFinishAllListeners()

        expect(logic.values.editingHogFunctionId).toBe('hf-slack')
        expect(logic.values.selectedType).toBe(ALERT_NOTIFICATION_TYPE_SLACK)
        expect(logic.values.slackChannelValue).toBe('C_OLD')
        expect(logic.values.webhookUrl).toBe('')

        logic.unmount()
    })

    it('pre-fills the webhook input when editing a webhook destination', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [WEBHOOK_HOG_FUNCTION],
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.startEditingHogFunction(WEBHOOK_HOG_FUNCTION)
        }).toFinishAllListeners()

        expect(logic.values.editingHogFunctionId).toBe('hf-webhook')
        expect(logic.values.selectedType).toBe(ALERT_NOTIFICATION_TYPE_WEBHOOK)
        expect(logic.values.webhookUrl).toBe('https://old.example/hook')
        expect(logic.values.slackChannelValue).toBe(null)

        logic.unmount()
    })

    it('clears the form when editing is cancelled', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.cancelEditingHogFunction()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingHogFunctionId).toBe(null)
        expect(logic.values.slackChannelValue).toBe(null)
        expect(logic.values.webhookUrl).toBe('')

        logic.unmount()
    })

    it('updates the underlying hog function in place when saving a slack edit', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })
        ;(mockApi.hogFunctions.update as jest.Mock).mockResolvedValue({
            ...SLACK_HOG_FUNCTION,
            inputs: {
                ...SLACK_HOG_FUNCTION.inputs,
                channel: { value: 'C_NEW' },
            },
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        // simulate the SlackChannelPicker emitting "id|#name"
        logic.actions.setSlackChannelValue('C_NEW|#new-channel')

        await expectLogic(logic, () => {
            logic.actions.saveEditingHogFunction()
        }).toFinishAllListeners()

        expect(mockApi.hogFunctions.update).toHaveBeenCalledTimes(1)
        expect(mockApi.hogFunctions.update).toHaveBeenCalledWith(
            'hf-slack',
            expect.objectContaining({
                inputs: expect.objectContaining({
                    channel: { value: 'C_NEW' },
                    // unrelated inputs must be preserved through the update
                    slack_workspace: { value: 1 },
                    message: { value: 'hello' },
                }),
            })
        )
        expect(lemonToast.success).toHaveBeenCalledWith('Notification updated.')
        expect(logic.values.editingHogFunctionId).toBe(null)

        logic.unmount()
    })

    it('updates the underlying hog function in place when saving a webhook edit', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [WEBHOOK_HOG_FUNCTION],
        })
        ;(mockApi.hogFunctions.update as jest.Mock).mockResolvedValue(WEBHOOK_HOG_FUNCTION)

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(WEBHOOK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setWebhookUrl('https://new.example/hook')

        await expectLogic(logic, () => {
            logic.actions.saveEditingHogFunction()
        }).toFinishAllListeners()

        expect(mockApi.hogFunctions.update).toHaveBeenCalledWith(
            'hf-webhook',
            expect.objectContaining({
                inputs: expect.objectContaining({
                    url: { value: 'https://new.example/hook' },
                    body: { value: { foo: 'bar' } },
                }),
            })
        )
        expect(logic.values.editingHogFunctionId).toBe(null)

        logic.unmount()
    })

    it('shows an error toast and keeps editing state when the update fails', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })
        ;(mockApi.hogFunctions.update as jest.Mock).mockRejectedValue(new Error('network'))

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSlackChannelValue('C_NEW|#new-channel')

        await expectLogic(logic, () => {
            logic.actions.saveEditingHogFunction()
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith(expect.stringContaining('Failed to update notification'))
        // Still in editing mode so the user can retry
        expect(logic.values.editingHogFunctionId).toBe('hf-slack')

        logic.unmount()
    })

    it('cancels editing when the destination being edited is deleted', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.editingHogFunctionId).toBe('hf-slack')

        logic.actions.deleteExistingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingHogFunctionId).toBe(null)

        logic.unmount()
    })

    it('does not call the API if the save action fires without a selected channel', async () => {
        ;(mockApi.hogFunctions.list as jest.Mock).mockResolvedValue({
            results: [SLACK_HOG_FUNCTION],
        })

        const logic = alertNotificationLogic({ alertId: 'alert-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.startEditingHogFunction(SLACK_HOG_FUNCTION)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSlackChannelValue(null)

        await expectLogic(logic, () => {
            logic.actions.saveEditingHogFunction()
        }).toFinishAllListeners()

        expect(mockApi.hogFunctions.update).not.toHaveBeenCalled()

        logic.unmount()
    })
})
