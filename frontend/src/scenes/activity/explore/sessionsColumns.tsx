import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { colonDelimitedDuration } from 'lib/utils'
import { urls } from 'scenes/urls'

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

    if (!isSessionsQuery(source)) {
        return (
            <Link to={urls.sessionProfile(sessionId)} className="font-mono">
                {sessionId}
            </Link>
        )
    }

    const endTimestampIndex = findColumnIndex(source.select, '$end_timestamp')
    const recordArray = Array.isArray(record) ? record : []
    const endTimestamp = endTimestampIndex !== -1 ? recordArray[endTimestampIndex] : null
    const isLive = isSessionLive(endTimestamp)

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
