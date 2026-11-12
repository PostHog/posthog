import { useValues } from 'kea'

import { AnalyticsMetricCard } from 'lib/components/AnalyticsMetricCard/AnalyticsMetricCard'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import {
    DefinitionInsightsLogicProps,
    DefinitionInsightsSummary,
    definitionInsightsLogic,
} from './definitionInsightsLogic'
import { DefinitionQueryUsage, DefinitionQueryUsageCard } from './DefinitionQueryUsageCard'
import { DefinitionUsageInsightsTable } from './DefinitionUsageInsightsTable'

export interface DefinitionUsageSectionProps {
    queryUsage: DefinitionQueryUsage | null
    queryUsageLoading: boolean
    queryUsageFailed: boolean
    insightsLogicProps: DefinitionInsightsLogicProps
    /** Shown first, for definitions whose captured volume can be counted. */
    eventVolumeCard?: JSX.Element
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
    queryUsage,
    queryUsageLoading,
    queryUsageFailed,
    insightsLogicProps,
    eventVolumeCard,
}: DefinitionUsageSectionProps): JSX.Element {
    const { summary, summaryLoading, summaryFailed } = useValues(definitionInsightsLogic(insightsLogicProps))
    const noun = insightsLogicProps.definitionType
    const hasNoInsights = summary?.insightCount === 0

    return (
        <SceneSection
            title="Usage"
            description={`How often this ${noun} was ${eventVolumeCard ? 'captured and ' : ''}queried in the last 30 days, and which saved insights use it.`}
        >
            <div className="flex flex-wrap gap-2">
                {eventVolumeCard}
                <DefinitionQueryUsageCard usage={queryUsage} loading={queryUsageLoading} failed={queryUsageFailed} />
                <AnalyticsMetricCard
                    className="flex-1 basis-60"
                    dataAttr="definition-usage-saved-insights"
                    title="Saved insights"
                    value={summary?.insightCount}
                    formatValue={formatCount}
                    showChange={false}
                    // Keeps the number under the title, level with the cards beside it that have sparklines.
                    changeBesideSubtitle
                    subtitle={summary ? dashboardsSubtitle(summary, noun) : undefined}
                    loading={summaryLoading}
                    error={summaryFailed ? "Couldn't load saved insights. Refresh the page to try again." : undefined}
                />
            </div>
            {!hasNoInsights && <DefinitionUsageInsightsTable logicProps={insightsLogicProps} />}
        </SceneSection>
    )
}
