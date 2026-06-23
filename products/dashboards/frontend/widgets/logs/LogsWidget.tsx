import { DetectiveHog } from 'lib/components/hedgehogs'

import {
    WIDGET_LIST_COUNT_LOGS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { LogsWidgetRow, LogsWidgetRowSkeleton, type LogsWidgetLogLine } from './LogsWidgetRow'

export type LogsWidgetResult = {
    results?: LogsWidgetLogLine[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

export function LogsWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as LogsWidgetResult | null | undefined
    const logLines = payload?.results ?? []

    if (loading) {
        return (
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {Array.from({ length: 6 }, (_, index) => (
                        <LogsWidgetRowSkeleton key={index} />
                    ))}
                </div>
            </WidgetCardContent>
        )
    }

    if (logLines.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="logs-widget-empty-state"
                    >
                        <DetectiveHog className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No logs found</p>
                        <p className="m-0 text-sm text-muted">
                            No logs matched your severity and service filters for this date range.
                        </p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {logLines.map((line) => (
                        <LogsWidgetRow key={line.uuid} line={line} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={logLines.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_LOGS}
                    hasMore={payload?.hasMore}
                    dataAttr="logs-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
