import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { MAX_SELECT_RETURNED_ROWS } from '~/queries/nodes/DataTable/DataTableExport'

interface SqlInsightRowLimitNoticeProps {
    dataLimit: number
}

/** Shown on chart and dashboard tile renders of a SQL insight when the result set was cut off by
 * the default row limit, so a truncated chart doesn't get mistaken for a stale cache. */
export function SqlInsightRowLimitNotice({ dataLimit }: SqlInsightRowLimitNoticeProps): JSX.Element {
    return (
        <Tooltip
            title={`Add "LIMIT ${dataLimit * 10}" (up to ${MAX_SELECT_RETURNED_ROWS}) to the query to see more rows`}
        >
            <div className="flex items-center gap-1 text-xs text-warning-dark cursor-help shrink-0 px-2">
                <IconWarning />
                Showing first {dataLimit} rows
            </div>
        </Tooltip>
    )
}
