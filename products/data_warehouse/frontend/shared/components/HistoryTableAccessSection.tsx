import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { historyTableAccessLogic } from 'products/data_warehouse/frontend/shared/logics/historyTableAccessLogic'

/** Offers to copy a table's access rules to its history table, from the table's access dialog. */
export function HistoryTableAccessSection({ tableId }: { tableId: string }): JSX.Element | null {
    const { historyTable, canCopyToHistoryTable, copyDisabledReason, copying } = useValues(
        historyTableAccessLogic({ tableId })
    )
    const { confirmCopyToHistoryTable } = useActions(historyTableAccessLogic({ tableId }))

    if (!historyTable || !canCopyToHistoryTable) {
        return null
    }

    return (
        <div className="mt-4 border rounded p-3 flex flex-wrap items-center justify-between gap-2">
            <p className="m-0 text-sm text-secondary flex-1 min-w-60">
                <span className="font-semibold text-primary">{historyTable.name}</span> keeps every past version of this
                table's rows. It has its own access rules, so changes here don't apply to it.
            </p>
            <LemonButton
                type="secondary"
                size="small"
                loading={copying}
                disabledReason={copyDisabledReason}
                onClick={confirmCopyToHistoryTable}
                data-attr="history-access-rules-copy"
            >
                Copy rules to the history table
            </LemonButton>
        </div>
    )
}
