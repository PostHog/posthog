import { useValues } from 'kea'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import {
    DefinitionInsightsLogicProps,
    DefinitionInsightsSummary,
    definitionInsightsLogic,
} from './definitionInsightsLogic'
import { DefinitionUsageInsightsTable } from './DefinitionUsageInsightsTable'

export interface DefinitionUsageSectionProps {
    queryCount: number | null
    queryCountLoading: boolean
    queryCountFailed: boolean
    insightsLogicProps: DefinitionInsightsLogicProps
}

const formatCount = (value: number): string => value.toLocaleString()

function dashboardsSubtitle(summary: DefinitionInsightsSummary, noun: string): string {
    if (summary.insightCount === 0) {
        return `No saved insights use this ${noun}`
    }
    const count = `${formatCount(summary.dashboardCount)}${summary.dashboardCountIsPartial ? '+' : ''}`
    return `On ${count} ${summary.dashboardCount === 1 && !summary.dashboardCountIsPartial ? 'dashboard' : 'dashboards'}`
}

export function DefinitionUsageSection({
    queryCount,
    queryCountLoading,
    queryCountFailed,
    insightsLogicProps,
}: DefinitionUsageSectionProps): JSX.Element {
    const { summary, summaryLoading, summaryFailed } = useValues(definitionInsightsLogic(insightsLogicProps))
    const noun = insightsLogicProps.definitionType
    const hasNoInsights = summary?.insightCount === 0

    return (
        <SceneSection
            title="Usage"
            description={`How often this ${noun} was queried in the last 30 days, and which saved insights use it.`}
        >
            <div className="flex flex-wrap gap-2">
                <AnalyticsMetricCard
                    className="flex-1 basis-60"
                    dataAttr="definition-usage-queries"
                    title="Queries"
                    value={queryCount ?? undefined}
                    formatValue={formatCount}
                    showChange={false}
                    subtitle={queryCount === 0 ? 'Not queried in the last 30 days' : 'In the last 30 days'}
                    loading={queryCountLoading}
                    error={
                        queryCountFailed ? "Couldn't load the query count. Refresh the page to try again." : undefined
                    }
                />
                <AnalyticsMetricCard
                    className="flex-1 basis-60"
                    dataAttr="definition-usage-saved-insights"
                    title="Saved insights"
                    value={summary?.insightCount}
                    formatValue={formatCount}
                    showChange={false}
                    subtitle={summary ? dashboardsSubtitle(summary, noun) : undefined}
                    loading={summaryLoading}
                    error={summaryFailed ? "Couldn't load saved insights. Refresh the page to try again." : undefined}
                />
            </div>
            {!hasNoInsights && <DefinitionUsageInsightsTable logicProps={insightsLogicProps} />}
        </SceneSection>
    )
}
