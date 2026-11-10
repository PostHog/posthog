import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/accessControlLogic'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { historyTableAccessLogic } from './historyTableAccessLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesHistoryTableRetrieve: jest.fn(),
    warehouseTablesCopyAccessRulesToHistoryTableCreate: jest.fn(),
}))

const dwApi = jest.requireMock('products/data_warehouse/frontend/generated/api')

const HISTORY_TABLE = { id: 'history-1', name: 'postgres.orders_history', user_can_manage_access: true }

describe('historyTableAccessLogic', () => {
    let logic: ReturnType<typeof historyTableAccessLogic.build>
    let dialog: jest.SpyInstance

    const mount = async (
        flagOn: boolean,
        historyTable: typeof HISTORY_TABLE | null,
        canManageTable = true
    ): Promise<void> => {
        const get = api.get
        jest.spyOn(api, 'get').mockImplementation((url: string, ...rest: any[]) =>
            url.endsWith('/access_controls')
                ? Promise.resolve({ access_controls: [], user_can_edit_access_levels: canManageTable })
                : get(url, ...rest)
        )
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_HISTORY_ACCESS_RULES]: flagOn })
        dwApi.warehouseTablesHistoryTableRetrieve.mockResolvedValue({ history_table: historyTable })
        logic = historyTableAccessLogic({ tableId: 'table-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        dwApi.warehouseTablesCopyAccessRulesToHistoryTableCreate.mockResolvedValue({ history_table: HISTORY_TABLE })
        dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => () => {})
    })

    afterEach(() => {
        logic?.unmount()
        jest.clearAllMocks()
        jest.restoreAllMocks()
    })

    it.each([
        ['the flag is on and the user can manage the history table', true, HISTORY_TABLE, true],
        ['the flag is off', false, HISTORY_TABLE, false],
        ['the user cannot manage the history table', true, { ...HISTORY_TABLE, user_can_manage_access: false }, false],
        ['the table has no history table', true, null, false],
        ['the user cannot manage the table', true, HISTORY_TABLE, false, false],
    ])('offers the copy only when %s', async (_name, flagOn, historyTable, expected, canManageTable = true) => {
        await mount(flagOn, historyTable, canManageTable)

        expect(logic.values.canCopyToHistoryTable).toBe(expected)
    })

    it.each([
        ['confirms', 'primaryButton', 1],
        ['cancels', 'secondaryButton', 0],
    ])('copies the rules only when the user %s', async (_name, button, copies) => {
        await mount(true, HISTORY_TABLE)

        logic.actions.confirmCopyToHistoryTable()
        dialog.mock.calls[0][0][button].onClick()
        await expectLogic(logic).toFinishAllListeners()

        expect(dwApi.warehouseTablesCopyAccessRulesToHistoryTableCreate).toHaveBeenCalledTimes(copies)
    })

    it('holds the copy while a rule change saves', async () => {
        await mount(true, HISTORY_TABLE)
        let finishSave: (value: unknown) => void = () => {}
        jest.spyOn(api, 'put').mockReturnValue(new Promise((resolve) => (finishSave = resolve)))
        const tableLogic = accessControlLogic({
            resource: AccessControlResourceType.WarehouseTable,
            resource_id: 'table-1',
            title: '',
            description: '',
        })

        tableLogic.actions.updateAccessControlDefault(AccessControlLevel.None)
        expect(logic.values.copyDisabledReason).not.toBeNull()

        finishSave({})
        await expectLogic(tableLogic).toFinishAllListeners()
        expect(logic.values.copyDisabledReason).toBeNull()
    })
})
