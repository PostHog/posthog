import { Tooltip } from '@posthog/lemon-ui'

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
            render: ({ value, record, query }) => {
                const sessionId = value as string
                const endTimestampIndex = query?.source?.select?.findIndex((field) => field === '$end_timestamp')
                const endTimestamp = record[endTimestampIndex]
                const isLive = endTimestamp && dayjs().diff(dayjs(endTimestamp), 'second') < 60
                return (
                    <div className="flex flex-row align-center items-center gap-2">
                        {isLive ? (
                            <Tooltip title="Live session">
                                <span className="relative flex h-2.5 w-2.5">
                                    <span
                                        className="absolute inline-flex h-full w-full rounded-full bg-danger animate-ping"
                                        style={{ opacity: 0.75 }}
                                    />
                                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-danger" />
                                </span>
                            </Tooltip>
                        ) : (
                            <span className="relative flex h-2.5 w-2.5" />
                        )}
                        <Link to={urls.sessionProfile(sessionId)} className="font-mono">
                            {sessionId}
                        </Link>
                    </div>
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

        if (rows.length === 0) {
            return rows
        }

        // Get the select columns from the SessionsQuery source
        const source = query.source as any
        const select = source?.select || []

        // Find the index of $start_timestamp in the select array
        const startTimestampIndex = select.findIndex(
            (col: string) => col === '$start_timestamp' || (typeof col === 'string' && col.includes('$start_timestamp'))
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
