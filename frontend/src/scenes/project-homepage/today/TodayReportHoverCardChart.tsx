import { Text } from '@posthog/quill'

import { Query } from '~/queries/Query/Query'
import type { Node } from '~/queries/schema/schema-general'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'
import { OBSERVATION_CHART_HEIGHT_CLASS } from 'products/signals/frontend/inbox/components/detail/ReportObservationChart'

/** A chart from the report body without its frame: its title, then the graph at the metric chart's height. */
export function TodayReportHoverCardChart({
    cardKey,
    chart,
    query,
}: {
    cardKey: string
    chart: ReportChartApi
    query: Node
}): JSX.Element {
    // The SQLEditor prefix lets a SQL graph size to its box rather than to the window.
    const uniqueKey = `SQLEditor-today-report-chart-${cardKey}-${chart.chart_id}`

    return (
        <div className="flex flex-col gap-1.5" data-attr="today-report-hover-card-chart">
            <Text size="xs" variant="muted" render={<span title={chart.title} />} className="truncate">
                {chart.title}
            </Text>
            <div className={`flex flex-col ${OBSERVATION_CHART_HEIGHT_CLASS}`}>
                {/* Keyed, so moving to another report's card does not reuse this chart's query logic. */}
                <Query key={uniqueKey} query={query} uniqueKey={uniqueKey} readOnly embedded />
            </div>
        </div>
    )
}
