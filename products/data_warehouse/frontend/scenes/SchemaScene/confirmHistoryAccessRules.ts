import api from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { captureAccessControlEvent } from 'lib/utils/accessControlUtils'

import { AccessControlResponseType, ExternalDataSourceSchema } from '~/types'

import { warehouseTablesHistoryTableRetrieve } from 'products/data_warehouse/frontend/generated/api'

type CdcTableMode = NonNullable<ExternalDataSourceSchema['cdc_table_mode']>

const HISTORY_MODES: CdcTableMode[] = ['cdc_only', 'both']

/** Whether saving this sync method starts writing a history table the schema didn't write before. */
export function turnsHistoryOn(
    schema: Pick<ExternalDataSourceSchema, 'sync_type' | 'cdc_table_mode'>,
    syncType: ExternalDataSourceSchema['sync_type'],
    cdcTableMode: CdcTableMode | undefined
): boolean {
    const keptHistory = schema.sync_type === 'cdc' && HISTORY_MODES.includes(schema.cdc_table_mode ?? 'consolidated')
    return syncType === 'cdc' && !!cdcTableMode && HISTORY_MODES.includes(cdcTableMode) && !keptHistory
}

async function tableHasOwnRulesYouCanCopy(projectId: number | string, tableId: string): Promise<boolean> {
    try {
        // nosemgrep: prefer-codegen-api -- the access_controls action is excluded from the OpenAPI schema, so no generated function covers it.
        const response = await api.get<AccessControlResponseType>(
            `api/projects/${projectId}/warehouse_tables/${tableId}/access_controls`
        )
        return response.user_can_edit_access_levels && response.access_controls.length > 0
    } catch {
        // Unknown, so ask: skipping the question would leave the history table on its source's rules.
        return true
    }
}

async function historyTableYouCannotManage(projectId: number | string, tableId: string): Promise<boolean> {
    try {
        const { history_table } = await warehouseTablesHistoryTableRetrieve(String(projectId), tableId)
        return !!history_table && !history_table.user_can_manage_access
    } catch {
        return false
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
    const [hasRules, cannotManageHistory] = await Promise.all([
        tableHasOwnRulesYouCanCopy(projectId, tableId),
        historyTableYouCannotManage(projectId, tableId),
    ])
    if (!hasRules || cannotManageHistory) {
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
