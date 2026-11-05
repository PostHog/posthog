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
}))

const dwApi = jest.requireMock('products/data_warehouse/frontend/generated/api')

const HISTORY_ENDPOINT = 'warehouse_tables/history-1/access_controls'

describe('historyTableAccessLogic', () => {
    let logic: ReturnType<typeof historyTableAccessLogic.build>
    let put: jest.SpyInstance
    let dialog: jest.SpyInstance

    const mount = async (flagOn: boolean, historyTable: { id: string; name: string } | null): Promise<void> => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WAREHOUSE_HISTORY_ACCESS_RULES]: flagOn })
        dwApi.warehouseTablesHistoryTableRetrieve.mockResolvedValue({ history_table: historyTable })
        logic = historyTableAccessLogic({ tableId: 'table-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    const changeDefaultRule = async (): Promise<void> => {
        const tableLogic = accessControlLogic({
            resource: AccessControlResourceType.WarehouseTable,
            resource_id: 'table-1',
            title: '',
            description: '',
        })
        await expectLogic(tableLogic, () =>
            tableLogic.actions.updateAccessControlDefault(AccessControlLevel.None)
        ).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()
    }

    const historyTablePuts = (): unknown[] =>
        put.mock.calls.filter(([url]) => String(url).endsWith(HISTORY_ENDPOINT)).map(([, body]) => body)

    beforeEach(() => {
        initKeaTests()
        put = jest.spyOn(api, 'put').mockResolvedValue({})
        dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => () => {})
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('repeats the rule change on the history table when the user accepts', async () => {
        await mount(true, { id: 'history-1', name: 'postgres.orders_history' })

        await changeDefaultRule()

        expect(dialog).toHaveBeenCalledTimes(1)
        expect(historyTablePuts()).toEqual([])
        dialog.mock.calls[0][0].primaryButton.onClick()
        await expectLogic(logic).toFinishAllListeners()

        expect(historyTablePuts()).toEqual([{ access_level: AccessControlLevel.None }])
    })

    it.each([
        ['the table has no history table', true, null],
        ['the flag is off', false, { id: 'history-1', name: 'postgres.orders_history' }],
    ])('asks nothing when %s', async (_name, flagOn, historyTable) => {
        await mount(flagOn, historyTable)

        await changeDefaultRule()

        expect(dialog).not.toHaveBeenCalled()
        expect(historyTablePuts()).toEqual([])
    })
})
