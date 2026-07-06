import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
} from 'lib/utils/alerts'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { alertNotificationLogic } from './alertNotificationLogic'

describe('alertNotificationLogic', () => {
    let logic: ReturnType<typeof alertNotificationLogic.build>
    let createSpy: jest.SpyInstance
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [], count: 0 })
        createSpy = jest
            .spyOn(api.hogFunctions, 'create')
            .mockImplementation(async (data) => ({ id: 'hf-1', ...data }) as HogFunctionType)
    })

    afterEach(() => {
        logic?.unmount()
        createSpy.mockRestore()
        listSpy.mockRestore()
    })

    it('clears staged inputs when the destination type changes', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        // A webhook URL entered for one destination must not carry over to another.
        logic.actions.setWebhookUrl('https://discord.com/api/webhooks/123/abc')
        await expectLogic(logic).toMatchValues({ webhookUrl: 'https://discord.com/api/webhooks/123/abc' })
        logic.actions.setSelectedType(ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS)
        await expectLogic(logic).toMatchValues({ webhookUrl: '' })

        // A staged Slack channel is cleared the same way.
        logic.actions.setSlackChannelValue('C123|#general')
        await expectLogic(logic).toMatchValues({ slackChannelValue: 'C123|#general' })
        logic.actions.setSelectedType(ALERT_NOTIFICATION_TYPE_WEBHOOK)
        await expectLogic(logic).toMatchValues({ slackChannelValue: null })
    })

    it('creates a Discord destination HogFunction end-to-end', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        // Drive the inline editor: pick Discord, enter a webhook URL, stage it
        logic.actions.setSelectedType(ALERT_NOTIFICATION_TYPE_DISCORD)
        logic.actions.setWebhookUrl('https://discord.com/api/webhooks/123/abc')
        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_DISCORD,
            webhookUrl: 'https://discord.com/api/webhooks/123/abc',
        })

        await expectLogic(logic).toMatchValues({
            pendingNotifications: [
                { type: ALERT_NOTIFICATION_TYPE_DISCORD, webhookUrl: 'https://discord.com/api/webhooks/123/abc' },
            ],
        })

        // Saving the alert flushes pending notifications through the real payload builder + API
        logic.actions.createPendingHogFunctions('alert-123', 'Daily revenue check')
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        const payload = createSpy.mock.calls[0][0]
        expect(payload.template_id).toBe('template-discord')
        expect(payload.name).toBe('Daily revenue check: Discord')
        expect(payload.enabled).toBe(true)
        expect(payload.inputs?.webhookUrl).toEqual({ value: 'https://discord.com/api/webhooks/123/abc' })
        expect(payload.inputs?.content?.value).toContain('{event.properties.alert_name}')

        await expectLogic(logic).toMatchValues({ pendingNotifications: [] })
    })

    it('creates a Microsoft Teams destination HogFunction end-to-end', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        // Drive the inline editor: pick Microsoft Teams, enter a webhook URL, stage it
        logic.actions.setSelectedType(ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS)
        logic.actions.setWebhookUrl('https://example.webhook.office.com/webhookb2/abc')
        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
            webhookUrl: 'https://example.webhook.office.com/webhookb2/abc',
        })

        await expectLogic(logic).toMatchValues({
            pendingNotifications: [
                {
                    type: ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
                    webhookUrl: 'https://example.webhook.office.com/webhookb2/abc',
                },
            ],
        })

        // Saving the alert flushes pending notifications through the real payload builder + API
        logic.actions.createPendingHogFunctions('alert-123', 'Daily revenue check')
        await expectLogic(logic).toFinishAllListeners()

        expect(createSpy).toHaveBeenCalledTimes(1)
        const payload = createSpy.mock.calls[0][0]
        expect(payload.template_id).toBe('template-microsoft-teams')
        expect(payload.name).toBe('Daily revenue check: Microsoft Teams')
        expect(payload.enabled).toBe(true)
        expect(payload.inputs?.webhookUrl).toEqual({ value: 'https://example.webhook.office.com/webhookb2/abc' })
        expect(payload.inputs?.text?.value).toContain('{event.properties.alert_name}')

        await expectLogic(logic).toMatchValues({ pendingNotifications: [] })
    })
})
