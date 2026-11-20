import { useValues } from 'kea'

import type { KnowledgeUsageApi, SurfaceUsageApi } from '../../generated/api.schemas'
import { businessKnowledgeUsageLogic } from './businessKnowledgeUsageLogic'
import { UsageMeterBreakdownRow, UsageMeterCard } from './UsageMeterCard'

// Keys are the `surface` values the backend records with each usage row.
const INGESTION_SOURCE_LABELS: Record<string, string> = {
    text: 'Text',
    url: 'Websites',
    file: 'Files',
    generated: 'Learned from support tickets',
}

const SEARCH_ORIGIN_LABELS: Record<string, string> = {
    api: 'API and MCP',
    support: 'Support agent',
    posthog_ai: 'PostHog AI',
    learning: 'Learning from support tickets',
}

function breakdownRows(usage: readonly SurfaceUsageApi[], labels: Record<string, string>): UsageMeterBreakdownRow[] {
    return usage.map(({ surface, total }) => ({ key: surface, label: labels[surface] ?? surface, total }))
}

export function UsageMeters({ usage }: { usage: KnowledgeUsageApi }): JSX.Element {
    const { usageLoading, dailyChunks, dailyQueries, dailyLabels } = useValues(businessKnowledgeUsageLogic)

    return (
        <div className="grid grid-cols-1 gap-2 @min-[48rem]/main-content:grid-cols-2">
            <UsageMeterCard
                label="Chunks ingested"
                total={usage.chunks_ingested}
                caption="PostHog splits each source into chunks. When a refresh finds changed content, its chunks count again."
                seriesName="Chunks"
                dailyCounts={dailyChunks}
                dailyLabels={dailyLabels}
                breakdownTitle="By source type"
                breakdown={breakdownRows(usage.chunks_by_surface, INGESTION_SOURCE_LABELS)}
                loading={usageLoading}
            />
            <UsageMeterCard
                label="Searches"
                total={usage.query_count}
                caption="Each time an agent or an API call searches your knowledge."
                seriesName="Searches"
                dailyCounts={dailyQueries}
                dailyLabels={dailyLabels}
                breakdownTitle="By where the search came from"
                breakdown={breakdownRows(usage.queries_by_surface, SEARCH_ORIGIN_LABELS)}
                loading={usageLoading}
            />
        </div>
    )
}
