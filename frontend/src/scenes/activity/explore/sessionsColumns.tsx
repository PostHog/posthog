import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { colonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isSessionsQuery } from '~/queries/utils'

export function getSessionsColumns(): QueryContext['columns'] {
    return {
        session_id: {
            title: 'Session ID',
            render: ({ value }) => {
                const sessionId = value as string
                return (
                    <Link to={urls.sessionProfile(sessionId)} className="font-mono">
                        {sessionId}
                    </Link>
                )
            },
        },
        $start_timestamp: {
            title: 'Start time',
            render: ({ value }) => <TZLabel time={value as string} showSeconds />,
        },
        $end_timestamp: {
            title: 'End time',
            render: ({ value }) => <TZLabel time={value as string} showSeconds />,
        },
        $session_duration: {
            title: 'Duration',
            render: ({ value }) => <>{colonDelimitedDuration(value as number)}</>,
        },
        $entry_current_url: {
            title: 'Entry URL',
        },
        $pageview_count: {
            title: 'Pageviews',
        },
        $is_bounce: {
            title: 'Bounced',
            render: ({ value }) => <>{value === 1 || value === true ? 'Yes' : 'No'}</>,
        },
    }
}

export function createSessionsRowTransformer(query: DataTableNode): (rows: DataTableRow[]) => DataTableRow[] {
    return (rows: DataTableRow[]): DataTableRow[] => {
        if (!isSessionsQuery(query.source)) {
            return rows
        }

        // Get the index of $start_timestamp column
        const columns = query.columns || []
        const startTimestampIndex = columns.findIndex(
            (col) => col === '$start_timestamp' || (typeof col === 'string' && col.includes('$start_timestamp'))
        )

        if (startTimestampIndex === -1) {
            return rows
        }

        // Add date labels between rows when the day changes
        let lastResult: any = null
        const newRows: DataTableRow[] = []

        for (const row of rows) {
            if (row.result && Array.isArray(row.result)) {
                const currentTimestamp = row.result[startTimestampIndex]
                if (
                    lastResult &&
                    currentTimestamp &&
                    !dayjs(currentTimestamp).isSame(lastResult[startTimestampIndex], 'day')
                ) {
                    newRows.push({
                        label: dayjs(currentTimestamp).format('LL'),
                    })
                }
                lastResult = row.result
            }
            newRows.push(row)
        }

        return newRows
    }
}
