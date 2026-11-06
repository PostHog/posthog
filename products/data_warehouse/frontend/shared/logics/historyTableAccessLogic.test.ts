import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

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

    const mount = async (flagOn: boolean, historyTable: typeof HISTORY_TABLE | null): Promise<void> => {
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
    ])('offers the copy only when %s', async (_name, flagOn, historyTable, expected) => {
        await mount(flagOn, historyTable)

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
})
