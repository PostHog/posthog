import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { formatBytes } from '../scenes/WarehouseConsole/warehouseConsoleFormat'
import { estimateSummary } from './estimateFormat'
import type { EstimateWarningTone } from './estimateFormat'
import { managedTrinoEstimateLogic } from './managedTrinoEstimateLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

const TONE_CLASS: Record<EstimateWarningTone, string> = {
    danger: 'text-danger',
    warning: 'text-warning-dark',
    muted: 'text-muted',
}

/** The pre-run scan estimate for a managed Trino query, shown beside the run button. It never blocks running. */
export function ManagedTrinoEstimate({ tabId }: { tabId: string }): JSX.Element | null {
    const { estimate, estimateStatus, estimateEnabled, warnings } = useValues(managedTrinoEstimateLogic({ tabId }))
    const { popoverOpened } = useActions(managedTrinoEstimateLogic({ tabId }))
    const [popoverVisible, setPopoverVisible] = useState(false)

    if (!estimateEnabled) {
        return null
    }
    if (estimateStatus === 'error' && !estimate) {
        return (
            <span className="text-xs text-muted" data-attr="sql-editor-estimate-unavailable">
                Estimate unavailable
            </span>
        )
    }
    if (!estimate) {
        return estimateStatus === 'loading' ? (
            <span className="flex items-center gap-1 text-xs text-muted" data-attr="sql-editor-estimate-loading">
                <Spinner className="text-sm" /> Estimating scan size
            </span>
        ) : null
    }

    const topWarning = warnings[0]

    return (
        <div
            className={`flex min-w-0 flex-wrap items-center gap-x-2 ${estimateStatus === 'loading' ? 'opacity-60' : ''}`}
            data-attr="sql-editor-estimate"
        >
            <Popover
                visible={popoverVisible}
                onClickOutside={() => setPopoverVisible(false)}
                placement="bottom-start"
                overlay={
                    <div className="max-w-120 space-y-2 p-3">
                        <div className="font-semibold">{estimateSummary(estimate)}</div>
                        <div className="text-xs text-muted">
                            An upper bound: the stored size of every table the query reads.
                        </div>
                        <ul className="m-0 list-none space-y-1 p-0">
                            {estimate.tables.map((table) => (
                                <li
                                    key={`${table.catalog}.${table.schema}.${table.table}`}
                                    className="flex flex-wrap justify-between gap-x-3 text-sm"
                                >
                                    <span className="font-mono">{`${table.schema}.${table.table}`}</span>
                                    <span className="text-muted">
                                        {table.size_bytes === null ? 'Size unknown' : formatBytes(table.size_bytes)}
                                        {' · '}
                                        {table.has_filter ? 'Filtered' : 'Not filtered'}
                                    </span>
                                </li>
                            ))}
                        </ul>
                        {warnings.map((warning) => (
                            <div key={warning.kind} className={`text-xs ${TONE_CLASS[warning.tone]}`}>
                                {warning.text}
                            </div>
                        ))}
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={() => {
                        if (!popoverVisible) {
                            popoverOpened()
                        }
                        setPopoverVisible(!popoverVisible)
                    }}
                    data-attr="sql-editor-estimate-summary"
                >
                    {estimateSummary(estimate)}
                </LemonButton>
            </Popover>
            {estimateStatus === 'loading' && <Spinner className="text-sm text-muted" />}
            {topWarning && <span className={`text-xs ${TONE_CLASS[topWarning.tone]}`}>{topWarning.text}</span>}
        </div>
    )
}
