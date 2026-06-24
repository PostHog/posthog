import { DetectiveHog } from 'lib/components/hedgehogs'

import {
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import {
    LlmAnalyticsTracesWidgetRow,
    LlmAnalyticsTracesWidgetRowSkeleton,
    type LlmAnalyticsTracesWidgetTrace,
} from './LlmAnalyticsTracesWidgetRow'

export type LlmAnalyticsTracesWidgetResult = {
    results?: LlmAnalyticsTracesWidgetTrace[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

const WIDGET_LIST_COUNT_TRACES = { singular: 'trace', plural: 'traces' }

export function LlmAnalyticsTracesWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as LlmAnalyticsTracesWidgetResult | null | undefined
    const traces = payload?.results ?? []

    if (loading) {
        return (
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {Array.from({ length: 5 }, (_, index) => (
                        <LlmAnalyticsTracesWidgetRowSkeleton key={index} />
                    ))}
                </div>
            </WidgetCardContent>
        )
    }

    if (traces.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="llm-analytics-traces-widget-empty-state"
                    >
                        <DetectiveHog className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No traces yet</p>
                        <p className="m-0 text-sm text-muted">No traces matched your filters for this date range.</p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {traces.map((trace) => (
                        <LlmAnalyticsTracesWidgetRow key={trace.id} trace={trace} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={traces.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_TRACES}
                    hasMore={payload?.hasMore}
                    dataAttr="llm-analytics-traces-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
