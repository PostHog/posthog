import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { warehouseAlertModalLogic } from './warehouseAlertModalLogic'
import { warehouseAlertNotificationLogic } from './warehouseAlertNotificationLogic'
import { warehouseAlertsLogic } from './warehouseAlertsLogic'

jest.mock('products/alerts_platform/frontend/generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsCreate: jest.fn(),
    platformAlertsUpdate: jest.fn(),
    platformAlertsDestroy: jest.fn(),
}))
jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataDestinationsList: jest.fn().mockResolvedValue({ results: [] }),
    warehouseAlertsDestinationsList: jest.fn().mockResolvedValue([]),
    warehouseAlertsDestinationsCreate: jest.fn().mockResolvedValue({ hog_function_ids: ['hog-1'] }),
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

    it('adds the destinations picked for a new alert once the alert exists', async () => {
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
        expect(notifications.values.pendingNotifications).toEqual([])
        expect(logic.values.isOpen).toBe(false)
    })

    it('reads every page of alerts, because the list cannot filter by kind', async () => {
        const logs = { id: 'logs', source_kind: 'logs', source_config: {} } as PlatformAlertConfigurationApi
        platformApi.platformAlertsList
            .mockResolvedValueOnce({ count: 2, next: 'page-2', results: [logs] })
            .mockResolvedValueOnce({ count: 2, next: null, results: [destinationAlert('on-page-2')] })
        const logic = warehouseAlertsLogic(PROPS)

        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()

        expect(logic.values.alerts?.map((alert) => alert.id)).toEqual(['on-page-2'])
    })
})
