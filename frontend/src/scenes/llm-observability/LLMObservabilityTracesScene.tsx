import { TZLabel } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { llmObservabilityLogic } from 'scenes/llm-observability/llmObservabilityLogic'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { LLMTrace } from '~/queries/schema'
import { QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

export function LLMObservabilityTraces(): JSX.Element {
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(llmObservabilityLogic)
    const { tracesQuery } = useValues(llmObservabilityLogic)
    return (
        <DataTable
            query={tracesQuery}
            setQuery={(query) => {
                if (!isTracesQuery(query.source)) {
                    throw new Error('Invalid query')
                }
                setDates(query.source.dateRange?.date_from || null, query.source.dateRange?.date_to || null)
                setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                setPropertyFilters(query.source.properties || [])
            }}
            context={{
                emptyStateHeading: 'There were no traces in this period',
                emptyStateDetail: 'Try changing the date range or filters.',
                columns: {
                    id: {
                        title: 'ID',
                    },
                    timestamp: {
                        title: 'Time',
                        render: TimestampColumn,
                    },
                    person: {
                        title: 'Person',
                    },
                    totalLatency: {
                        title: 'Latency',
                        render: LatencyColumn,
                    },
                    usage: {
                        title: 'Token Usage',
                        render: UsageColumn,
                    },
                    totalCost: {
                        title: 'Total Cost',
                        render: CostColumn,
                    },
                },
            }}
            uniqueKey="llm-observability-traces"
        />
    )
}

const TimestampColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return <TZLabel time={row.createdAt} />
}
TimestampColumn.displayName = 'TimestampColumn'

const LatencyColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalLatency === 'number') {
        return <>{row.totalLatency}s</>
    }
    return <>–</>
}
LatencyColumn.displayName = 'LatencyColumn'

const UsageColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.inputTokens === 'number') {
        return (
            <>
                {row.inputTokens} → {row.outputTokens || 0} (∑ {row.inputTokens + (row.outputTokens || 0)})
            </>
        )
    }

    return <>–</>
}
UsageColumn.displayName = 'UsageColumn'

const CostColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalCost === 'number') {
        return <>${row.totalCost}</>
    }
    return <>–</>
}
CostColumn.displayName = 'CostColumn'
