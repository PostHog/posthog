import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { ExternalDataSourceSchema } from '~/types'

import { confirmHistoryAccessRules, turnsHistoryOn } from './confirmHistoryAccessRules'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    warehouseTablesHistoryTableRetrieve: jest.fn(),
}))

const dwApi = jest.requireMock('products/data_warehouse/frontend/generated/api')

type Mode = ExternalDataSourceSchema['cdc_table_mode']

describe('confirmHistoryAccessRules', () => {
    let dialog: jest.SpyInstance
    let save: jest.Mock
    let cancel: jest.Mock

    const ask = async ({
        ownRules = true,
        historyTable = null as { user_can_manage_access: boolean } | null,
    } = {}): Promise<void> => {
        dwApi.warehouseTablesHistoryTableRetrieve.mockResolvedValue({
            history_table: historyTable,
            main_table_has_copyable_rules: ownRules,
        })
        await confirmHistoryAccessRules(1, 'table-1', save, cancel)
    }

    const close = (button?: 'primaryButton' | 'secondaryButton'): void => {
        const props = dialog.mock.calls[0][0]
        if (button) {
            props[button].onClick()
        }
        props.onAfterClose()
    }

    beforeEach(() => {
        dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => () => {})
        save = jest.fn()
        cancel = jest.fn()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        ['accepts', 'primaryButton' as const, [[true]], 0],
        ['declines', 'secondaryButton' as const, [[false]], 0],
        ['closes the dialog', undefined, [], 1],
    ])('saves with the answer when the user %s', async (_name, button, saves, cancels) => {
        await ask()

        close(button)

        expect(save.mock.calls).toEqual(saves)
        expect(cancel).toHaveBeenCalledTimes(cancels)
    })

    it.each([
        ['the table has no rules of its own', { ownRules: false }],
        ['the user cannot manage the history table', { historyTable: { user_can_manage_access: false } }],
    ])('saves without asking when %s', async (_name, options) => {
        await ask(options)

        expect(dialog).not.toHaveBeenCalled()
        expect(save.mock.calls).toEqual([[false]])
    })

    it('asks when the lookup fails, rather than leaving the history table on its source rules', async () => {
        dwApi.warehouseTablesHistoryTableRetrieve.mockRejectedValue(new Error('down'))

        await confirmHistoryAccessRules(1, 'table-1', save, cancel)

        expect(dialog).toHaveBeenCalledTimes(1)
        expect(save).not.toHaveBeenCalled()
    })

    type SyncType = ExternalDataSourceSchema['sync_type']
    it.each<[string, SyncType, Mode, SyncType, Mode, boolean]>([
        ['consolidated to both', 'cdc', 'consolidated', 'cdc', 'both', true],
        ['consolidated to cdc_only', 'cdc', 'consolidated', 'cdc', 'cdc_only', true],
        ['incremental to cdc with history', 'incremental', undefined, 'cdc', 'both', true],
        ['cdc_only to both', 'cdc', 'cdc_only', 'cdc', 'both', false],
        ['both to consolidated', 'cdc', 'both', 'cdc', 'consolidated', false],
        ['incremental turning history on', 'incremental', 'consolidated', 'incremental', 'both', true],
        ['incremental keeping history', 'incremental', 'both', 'incremental', 'cdc_only', false],
        ['cdc with history to incremental with history', 'cdc', 'both', 'incremental', 'both', false],
    ])('turnsHistoryOn: %s', (_name, savedSyncType, savedMode, newSyncType, newMode, expected) => {
        expect(turnsHistoryOn({ sync_type: savedSyncType, cdc_table_mode: savedMode }, newSyncType, newMode)).toBe(
            expected
        )
    })
})
