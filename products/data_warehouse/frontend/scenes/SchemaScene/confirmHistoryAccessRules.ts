import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { captureAccessControlEvent } from 'lib/utils/accessControlUtils'

import { ExternalDataSourceSchema } from '~/types'

import { warehouseTablesHistoryTableRetrieve } from 'products/data_warehouse/frontend/generated/api'

import { writesHistoryTable } from './historyTable'

type CdcTableMode = NonNullable<ExternalDataSourceSchema['cdc_table_mode']>

/** Whether saving this sync method starts writing a history table the schema didn't write before. */
export function turnsHistoryOn(
    schema: Pick<ExternalDataSourceSchema, 'sync_type' | 'cdc_table_mode'>,
    syncType: ExternalDataSourceSchema['sync_type'],
    cdcTableMode: CdcTableMode | undefined
): boolean {
    return writesHistoryTable(syncType, cdcTableMode) && !writesHistoryTable(schema.sync_type, schema.cdc_table_mode)
}

async function hasRulesToCopy(projectId: number | string, tableId: string): Promise<boolean> {
    try {
        const response = await warehouseTablesHistoryTableRetrieve(String(projectId), tableId)
        const historyTable = response.history_table
        return response.main_table_has_copyable_rules && (!historyTable || historyTable.user_can_manage_access)
    } catch {
        // Unknown, so ask: skipping the question would leave the history table on its source's rules.
        return true
    }
}

/** Ask whether the history table should start with the table's access rules, then save with the answer.
 * `cancel` runs when the user closes the dialog without answering, so nothing saves. */
export async function confirmHistoryAccessRules(
    projectId: number | string,
    tableId: string,
    save: (copyAccessRules: boolean) => void,
    cancel: () => void
): Promise<void> {
    if (!(await hasRulesToCopy(projectId, tableId))) {
        save(false)
        return
    }
    captureAccessControlEvent('history table access rules offered', { trigger: 'history_turned_on' })
    let answered = false
    const answer = (accepted: boolean): void => {
        answered = true
        captureAccessControlEvent('history table access rules answered', { trigger: 'history_turned_on', accepted })
        save(accepted)
    }
    LemonDialog.open({
        title: 'Give the history table the same access rules?',
        description:
            "This table has its own access rules. The history table is a separate table, so those rules don't apply to it. Copy them so the history table starts with the same rules. This replaces the history table's current rules.",
        primaryButton: {
            children: 'Copy access rules',
            type: 'primary',
            onClick: () => answer(true),
            'data-attr': 'history-access-rules-copy',
        },
        secondaryButton: {
            children: "Don't copy",
            type: 'secondary',
            onClick: () => answer(false),
            'data-attr': 'history-access-rules-skip',
        },
        onAfterClose: () => {
            if (!answered) {
                cancel()
            }
        },
    })
}
