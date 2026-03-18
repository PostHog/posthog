import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { colonDelimitedDuration } from 'lib/utils'
import { SessionDisplay } from 'scenes/sessions/SessionDisplay'

import { DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableNode, SessionsQuery } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent } from '~/queries/types'
import { isSessionsQuery } from '~/queries/utils'

function isSessionLive(endTimestamp: unknown): boolean {
    if (!endTimestamp) {
        return false
    }
    return dayjs().diff(dayjs(endTimestamp as string), 'second') < 60
}

function findColumnIndex(select: SessionsQuery['select'], columnName: string): number {
    if (!select) {
        return -1
    }
    return select.findIndex(
        (field) => field === columnName || (typeof field === 'string' && field.includes(columnName))
    )
}

const renderSessionId: QueryContextColumnComponent = ({ value, record, query }) => {
    const sessionId = value as string
    const source = query.source

    let isLive = false
    if (isSessionsQuery(source)) {
        const endTimestampIndex = findColumnIndex(source.select, '$end_timestamp')
        const recordArray = Array.isArray(record) ? record : []
        const endTimestamp = endTimestampIndex !== -1 ? recordArray[endTimestampIndex] : null
        isLive = isSessionLive(endTimestamp)
    }

    return <SessionDisplay sessionId={sessionId} isLive={isLive} noPopover />
}

export function getSessionsColumns(): QueryContext['columns'] {
    return {
        session_id: {
            title: 'Session ID',
            render: renderSessionId,
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
        if (!isSessionsQuery(query.source) || rows.length === 0) {
            return rows
        }

        const source = query.source
        const startTimestampIndex = findColumnIndex(source.select, '$start_timestamp')

        if (startTimestampIndex === -1) {
            return rows
        }

        let lastTimestamp: string | null = null
        const newRows: DataTableRow[] = []

        for (const row of rows) {
            if (row.result && Array.isArray(row.result)) {
                const currentTimestamp = row.result[startTimestampIndex] as string | undefined

                if (lastTimestamp && currentTimestamp && !dayjs(currentTimestamp).isSame(dayjs(lastTimestamp), 'day')) {
                    newRows.push({
                        label: dayjs(currentTimestamp).format('LL'),
                    })
                }

                if (currentTimestamp) {
                    lastTimestamp = currentTimestamp
                }
            }
            newRows.push(row)
        }

        return newRows
    }
}
