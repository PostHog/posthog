import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import {
    alertsDestinationsDeleteCreate,
    alertsDestinationsList,
    alertsDestinationsPagerdutyCreate,
    alertsDestinationsWebhookCreate,
    alertsTestDeliveryCreate,
} from 'products/alerts/frontend/generated/api'
import type { AlertDestinationListItemApi } from 'products/alerts/frontend/generated/api.schemas'
import {
    ALERT_NOTIFICATION_TYPE_DISCORD,
    ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS,
    ALERT_NOTIFICATION_TYPE_PAGERDUTY,
    ALERT_NOTIFICATION_TYPE_SLACK,
    ALERT_NOTIFICATION_TYPE_WEBHOOK,
} from 'products/alerts/frontend/logic/alertNotifications'

import { alertNotificationLogic } from './alertNotificationLogic'

jest.mock('products/alerts/frontend/generated/api', () => ({
    alertsDestinationsCreate: jest.fn(),
    alertsDestinationsDeleteCreate: jest.fn(),
    alertsDestinationsList: jest.fn(),
    alertsDestinationsPagerdutyCreate: jest.fn(),
    alertsDestinationsWebhookCreate: jest.fn(),
    alertsTestDeliveryCreate: jest.fn(),
}))

describe('alertNotificationLogic', () => {
    let logic: ReturnType<typeof alertNotificationLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(alertsDestinationsList).mockResolvedValue([])
        jest.mocked(alertsDestinationsWebhookCreate).mockResolvedValue({ hog_function_ids: ['hf-1'] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const makeSlackIntegration = (id: number): IntegrationType => ({
        id,
        kind: 'slack',
        display_name: `Workspace ${id}`,
        icon_url: '',
        config: {},
        created_at: '2026-01-01T00:00:00Z',
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
        logic.actions.setSelectedSlackIntegrationId(2)
        await expectLogic(logic).toMatchValues({ slackChannelValue: null })

        logic.actions.setSlackChannelValue('C456|#alerts')
        logic.actions.setSelectedType(ALERT_NOTIFICATION_TYPE_WEBHOOK)
        await expectLogic(logic).toMatchValues({ slackChannelValue: null })
    })

    it('selects a Slack workspace that loaded before the alert logic mounted', async () => {
        const workspace = makeSlackIntegration(1)
        const integrationsListSpy = jest.spyOn(api.integrations, 'list').mockReturnValue(new Promise(() => {}))
        const unmountIntegrations = integrationsLogic.mount()
        integrationsLogic.actions.loadIntegrationsSuccess([workspace])
        await expectLogic(integrationsLogic).toMatchValues({ slackIntegrations: [workspace] })

        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        await expectLogic(logic).toMatchValues({ selectedSlackIntegration: workspace })

        unmountIntegrations()
        integrationsListSpy.mockRestore()
    })

    it('tracks integration loading failures until a retry succeeds', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        logic.actions.loadIntegrationsFailure('Network error')
        await expectLogic(logic).toMatchValues({ integrationsFailed: true })

        logic.actions.loadIntegrations()
        await expectLogic(logic).toMatchValues({ integrationsFailed: false })

        logic.actions.loadIntegrationsSuccess([])
        await expectLogic(logic).toMatchValues({ integrationsFailed: false })
    })

    it('sends a test delivery for the saved alert', async () => {
        jest.mocked(alertsTestDeliveryCreate).mockResolvedValue({
            destination_count: 2,
            email_recipient_count: 1,
            failed_delivery_channels: [],
        })
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        logic.actions.sendTestDelivery()
        await expectLogic(logic).toFinishAllListeners()

        expect(alertsTestDeliveryCreate).toHaveBeenCalledWith('997', 'alert-123')
        await expectLogic(logic).toMatchValues({
            testDeliveryResult: { destination_count: 2, email_recipient_count: 1, failed_delivery_channels: [] },
        })
    })

    it('clears the channel when an integrations refresh removes the selected workspace', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])
        await expectLogic(logic).toMatchValues({ selectedSlackIntegrationId: 1 })

        logic.actions.setSelectedSlackIntegrationId(2)
        logic.actions.setSlackChannelValue('C123|#general')
        logic.actions.loadIntegrationsSuccess([firstWorkspace])

        await expectLogic(logic).toMatchValues({
            selectedSlackIntegrationId: 1,
            selectedSlackIntegration: firstWorkspace,
            slackChannelValue: null,
        })
    })

    it('drops staged Slack notifications for a workspace removed by an integrations refresh', async () => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        const firstWorkspace = makeSlackIntegration(1)
        const secondWorkspace = makeSlackIntegration(2)
        logic.actions.loadIntegrationsSuccess([firstWorkspace, secondWorkspace])

        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_SLACK,
            slackWorkspaceId: 2,
            slackChannelId: 'C1',
            slackChannelName: 'general',
        })
        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_WEBHOOK,
            webhookUrl: 'https://example.com',
        })
        await expectLogic(logic).toMatchValues({ pendingNotifications: [expect.anything(), expect.anything()] })

        logic.actions.loadIntegrationsSuccess([firstWorkspace])

        // The staged Slack destination pointed at the now-removed workspace 2 is dropped;
        // saving it would create a HogFunction referencing a dead integration. The webhook
        // notification doesn't reference a workspace, so it's untouched.
        await expectLogic(logic).toMatchValues({
            pendingNotifications: [{ type: ALERT_NOTIFICATION_TYPE_WEBHOOK, webhookUrl: 'https://example.com' }],
        })
    })

    it.each([
        [ALERT_NOTIFICATION_TYPE_DISCORD, 'https://discord.com/api/webhooks/123/abc', 'discord'],
        [ALERT_NOTIFICATION_TYPE_MICROSOFT_TEAMS, 'https://example.webhook.office.com/webhookb2/abc', 'teams'],
        [ALERT_NOTIFICATION_TYPE_WEBHOOK, 'https://example.com/hook', 'webhook'],
    ] as const)('creates a %s destination through the alert API', async (type, webhookUrl, apiType) => {
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()
        logic.actions.addPendingNotification({ type, webhookUrl })

        logic.actions.createPendingDestinations('alert-123')
        await expectLogic(logic).toFinishAllListeners()

        expect(alertsDestinationsWebhookCreate).toHaveBeenCalledWith(expect.any(String), 'alert-123', {
            type: apiType,
            webhook_url: webhookUrl,
        })
        await expectLogic(logic).toMatchValues({ pendingNotifications: [] })
    })

    it('creates and removes a PagerDuty destination through the alert API', async () => {
        jest.mocked(alertsDestinationsPagerdutyCreate).mockResolvedValue({ hog_function_ids: ['hf-open', 'hf-close'] })
        jest.mocked(alertsDestinationsDeleteCreate).mockResolvedValue(undefined)
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_PAGERDUTY,
            routingKey: 'a'.repeat(32),
            severity: 'error',
            region: 'eu',
        })
        logic.actions.createPendingDestinations('alert-123')
        await expectLogic(logic).toFinishAllListeners()

        expect(alertsDestinationsPagerdutyCreate).toHaveBeenCalledWith(expect.any(String), 'alert-123', {
            pagerduty_routing_key: 'a'.repeat(32),
            pagerduty_severity: 'error',
            pagerduty_region: 'eu',
        })
        await expectLogic(logic).toMatchValues({ pendingNotifications: [] })

        logic.actions.deleteDestination({
            id: 'row-1',
            hog_function_ids: ['hf-open', 'hf-close'],
            type: 'pagerduty',
        } as AlertDestinationListItemApi)
        await expectLogic(logic).toFinishAllListeners()

        expect(alertsDestinationsDeleteCreate).toHaveBeenCalledWith(expect.any(String), 'alert-123', {
            hog_function_ids: ['hf-open', 'hf-close'],
        })
    })

    it('removes a destination whose HogFunctions are gone by its platform id', async () => {
        jest.mocked(alertsDestinationsDeleteCreate).mockResolvedValue(undefined)
        logic = alertNotificationLogic({ alertId: 'alert-123' })
        logic.mount()

        logic.actions.deleteDestination({
            id: 'row-1',
            hog_function_ids: [],
            type: 'slack',
        } as unknown as AlertDestinationListItemApi)
        await expectLogic(logic).toFinishAllListeners()

        expect(alertsDestinationsDeleteCreate).toHaveBeenCalledWith(expect.any(String), 'alert-123', {
            destination_ids: ['row-1'],
        })
    })

    it('drops a staged PagerDuty notification when the new alert can no longer page', async () => {
        logic = alertNotificationLogic({})
        logic.mount()
        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_PAGERDUTY,
            routingKey: 'a'.repeat(32),
            severity: 'critical',
            region: 'us',
        })
        logic.actions.addPendingNotification({
            type: ALERT_NOTIFICATION_TYPE_WEBHOOK,
            webhookUrl: 'https://example.com',
        })

        logic.actions.loadNewAlertPagerDutyAvailableSuccess(false)

        await expectLogic(logic).toMatchValues({
            pendingNotifications: [{ type: ALERT_NOTIFICATION_TYPE_WEBHOOK, webhookUrl: 'https://example.com' }],
        })
    })
})
