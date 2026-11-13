import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { warehouseAlertModalLogic } from './warehouseAlertModalLogic'
import { warehouseAlertNotificationLogic } from './warehouseAlertNotificationLogic'
import { warehouseAlertsLogic } from './warehouseAlertsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))
jest.mock('products/alerts_platform/frontend/generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsCreate: jest.fn(),
    platformAlertsUpdate: jest.fn(),
    platformAlertsDestroy: jest.fn(),
}))
jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataDestinationsList: jest.fn().mockResolvedValue({ results: [] }),
    warehouseAlertsDestinationsList: jest.fn().mockResolvedValue([]),
    warehouseAlertsDestinationsCreate: jest.fn(),
    warehouseAlertsDestinationsDeleteCreate: jest.fn(),
}))

const platformApi = jest.requireMock('products/alerts_platform/frontend/generated/api')
const warehouseApi = jest.requireMock('products/warehouse_sources/frontend/generated/api')

const PROPS = { kind: 'warehouse_destination' } as const

function destinationAlert(id: string): PlatformAlertConfigurationApi {
    return { id, source_kind: 'warehouse_destination', source_config: {} } as PlatformAlertConfigurationApi
}

describe('warehouse alert logics', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        platformApi.platformAlertsList.mockResolvedValue({ count: 0, next: null, results: [] })
    })

    it.each([
        ['adds it', () => Promise.resolve({ id: 'destination-1' }), 0, undefined],
        [
            'shows the reason the API refused it, and drops it',
            () => Promise.reject({ status: 400, detail: 'This alert already sends to this destination.' }),
            0,
            "Couldn't add 1 notification destination. This alert already sends to this destination.",
        ],
        [
            'keeps it to send again after a failure without a reason',
            () => Promise.reject(new Error('Network error')),
            1,
            "Couldn't add 1 notification destination. Open the alert and add it again.",
        ],
    ])('for a destination picked for a new alert, once the alert exists, %s', async (_, create, pendingLeft, toast) => {
        warehouseApi.warehouseAlertsDestinationsCreate.mockImplementation(create)
        platformApi.platformAlertsCreate.mockResolvedValue(destinationAlert('new-alert'))
        const logic = warehouseAlertModalLogic(PROPS)
        logic.mount()
        const notifications = warehouseAlertNotificationLogic({})
        notifications.mount()

        logic.actions.openForCreate('destination_row', ['destination-a'])
        notifications.actions.addPendingNotification({ type: 'webhook', webhook_url: 'https://example.com/hook' })
        await expectLogic(logic, () => logic.actions.submitAlertForm()).toFinishAllListeners()

        expect(platformApi.platformAlertsCreate).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({
                source_config: { destination_ids: ['destination-a'], email_project_members: true },
            })
        )
        expect(warehouseApi.warehouseAlertsDestinationsCreate).toHaveBeenCalledWith(expect.any(String), 'new-alert', {
            type: 'webhook',
            webhook_url: 'https://example.com/hook',
        })
        expect(notifications.values.pendingNotifications).toHaveLength(pendingLeft)
        expect(logic.values.isOpen).toBe(false)
        expect(jest.mocked(lemonToast.error).mock.calls).toEqual(toast ? [[toast]] : [])
    })

    it.each([
        ['the alert has the most destinations it can have', 5, 'https://example.com/other', 'at most 5 destinations'],
        [
            'the destination is already in the list',
            1,
            'https://example.com/hook-0',
            'already sends to this destination',
        ],
    ])('blocks another destination when %s', (_, pendingCount, webhookUrl, reason) => {
        const notifications = warehouseAlertNotificationLogic({})
        notifications.mount()
        notifications.actions.setSelectedType('webhook')
        notifications.actions.setPendingNotifications(
            Array.from({ length: pendingCount }, (_, index) => ({
                type: 'webhook' as const,
                webhook_url: `https://example.com/hook-${index}`,
            }))
        )
        notifications.actions.setWebhookUrl(webhookUrl)

        expect(notifications.values.addDisabledReason).toContain(reason)
    })

    it('asks only for the alerts of its kind, and reads every page', async () => {
        platformApi.platformAlertsList
            .mockResolvedValueOnce({ count: 2, next: 'page-2', results: [destinationAlert('on-page-1')] })
            .mockResolvedValueOnce({ count: 2, next: null, results: [destinationAlert('on-page-2')] })
        const logic = warehouseAlertsLogic(PROPS)

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(platformApi.platformAlertsList).toHaveBeenCalledWith(
            expect.any(String),
            expect.objectContaining({ source_kind: 'warehouse_destination', offset: 0 })
        )
        expect(logic.values.alerts?.map((alert) => alert.id)).toEqual(['on-page-1', 'on-page-2'])
    })
})
