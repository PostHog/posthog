import { Link, TZLabel, urls } from '@posthog/apps-common'
import { useActions, useValues } from 'kea'
import { llmObservabilityLogic } from 'scenes/llm-observability/llmObservabilityLogic'

import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { LLMTrace } from '~/queries/schema'
import { QueryContextColumnComponent } from '~/queries/types'
import { isTracesQuery } from '~/queries/utils'

import { formatLLMCost, formatLLMUsage } from './utils'

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
                        render: IDColumn,
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

const IDColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    return (
        <Link className="ph-no-capture font-semibold" to={urls.llmObservabilityTrace(row.id)}>
            {row.id}
        </Link>
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
    const usage = formatLLMUsage(row)
    return <>{usage || '–'}</>
}
UsageColumn.displayName = 'UsageColumn'

const CostColumn: QueryContextColumnComponent = ({ record }) => {
    const row = record as LLMTrace
    if (typeof row.totalCost === 'number') {
        return <>{formatLLMCost(row.totalCost)}</>
    }
    return <>–</>
}
CostColumn.displayName = 'CostColumn'
