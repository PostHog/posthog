import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import { warehouseAlertsLogic } from './warehouseAlertsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))
jest.mock('products/alerts_platform/frontend/generated/api', () => ({
    platformAlertsList: jest.fn(),
    platformAlertsDestroy: jest.fn(),
    platformAlertsPartialUpdate: jest.fn(),
}))
jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataDestinationsList: jest.fn().mockResolvedValue({ results: [] }),
}))

const platformApi = jest.requireMock('products/alerts_platform/frontend/generated/api')

const PROPS = { kind: 'warehouse_source' } as const

function alert(id: string, overrides: Record<string, unknown> = {}): PlatformAlertConfigurationApi {
    return {
        id,
        name: `Alert ${id}`,
        enabled: true,
        source_kind: 'warehouse_source',
        source_config: { source_ids: [] },
        created_by: { uuid: 'user-a' },
        ...overrides,
    } as unknown as PlatformAlertConfigurationApi
}

const ALERTS = [
    alert('1', { name: 'Stripe failures' }),
    alert('2', { name: 'Paused one', enabled: false }),
    alert('3', { name: 'Other', created_by: { uuid: 'user-b' }, source_config: { source_ids: ['s1'] } }),
]

describe('warehouseAlertsLogic filters', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        platformApi.platformAlertsList.mockResolvedValue({ count: 3, next: null, results: ALERTS })
        platformApi.platformAlertsPartialUpdate.mockResolvedValue({})
    })

    it.each([
        ['hides paused alerts by default', {}, ['1', '3'], 1],
        ['shows paused alerts on request', { showPaused: true }, ['1', '2', '3'], 0],
        ['matches the name without case', { search: 'STRIPE' }, ['1'], 0],
        ['matches a watched source id when it has no label', { search: 's1' }, ['3'], 0],
        ['filters by creator', { createdBy: 'user-b' }, ['3'], 0],
        ['counts a matching paused alert as hidden', { search: 'paused' }, [], 1],
    ])('%s', async (_, filters, expectedIds, hidden) => {
        const logic = warehouseAlertsLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setFilters(filters)

        expect(logic.values.filteredAlerts.map((a) => a.id)).toEqual(expectedIds)
        expect(logic.values.hiddenAlertCount).toEqual(hidden)
    })

    it('resets the filters', async () => {
        const logic = warehouseAlertsLogic(PROPS)
        logic.mount()
        logic.actions.setFilters({ search: 'x', showPaused: true, createdBy: 'user-a' })
        logic.actions.resetFilters()

        expect(logic.values.filters).toEqual({ search: '', createdBy: null, showPaused: false })
    })

    it('pauses an alert with only the enabled flag and reloads the list', async () => {
        const logic = warehouseAlertsLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.toggleAlertEnabled(ALERTS[0], false)
        await expectLogic(logic).toFinishAllListeners()

        expect(platformApi.platformAlertsPartialUpdate).toHaveBeenCalledWith(expect.any(String), '1', {
            source_kind: 'warehouse_source',
            enabled: false,
        })
        expect(platformApi.platformAlertsList).toHaveBeenCalledTimes(2)
        expect(logic.values.togglingAlertId).toBeNull()
    })
})
