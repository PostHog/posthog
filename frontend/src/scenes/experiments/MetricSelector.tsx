import { BindLogic, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FilterType, InsightShortId, InsightType } from '~/types'
import './Experiment.scss'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'
import { trendsLogic } from 'scenes/trends/trendsLogic'

export interface MetricSelectorProps {
    createPreviewInsight: (filters?: Partial<FilterType>) => void
    setFilters: (filters: Partial<FilterType>) => void
    previewInsightId: InsightShortId | null
    filters: Partial<FilterType>
}

export function MetricSelector({
    createPreviewInsight,
    previewInsightId,
    filters,
    setFilters,
}: MetricSelectorProps): JSX.Element {
    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: previewInsightId as InsightShortId,
            syncWithUrl: false,
        })
    )

    const { isStepsEmpty, filterSteps, filters: funnelsFilters } = useValues(funnelLogic(insightProps))
    const { filters: trendsFilters } = useValues(trendsLogic(insightProps))

    const experimentInsightType = filters.insight

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    value={experimentInsightType}
                    onChange={(val) => {
                        val && createPreviewInsight({ insight: val })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {experimentInsightType === InsightType.FUNNELS && (
                <ActionFilter
                    bordered
                    filters={funnelsFilters}
                    setFilters={(payload) => {
                        setFilters({
                            ...filters,
                            insight: InsightType.FUNNELS,
                            ...payload,
                        })
                    }}
                    typeKey={`experiment-funnel-goal-${JSON.stringify(filters)}`}
                    mathAvailability={MathAvailability.None}
                    hideDeleteBtn={filterSteps.length === 1}
                    buttonCopy="Add funnel step"
                    showSeriesIndicator={!isStepsEmpty}
                    seriesIndicatorType="numeric"
                    sortable
                    showNestedArrow={true}
                    propertiesTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                    ]}
                />
            )}
            {experimentInsightType === InsightType.TRENDS && (
                <ActionFilter
                    bordered
                    filters={trendsFilters}
                    setFilters={(payload: Partial<FilterType>) => {
                        setFilters({
                            ...filters,
                            insight: InsightType.TRENDS,
                            ...payload,
                        })
                    }}
                    typeKey={`experiment-trends-goal-${JSON.stringify(filters)}`}
                    buttonCopy="Add graph series"
                    showSeriesIndicator
                    entitiesLimit={1}
                    hideDeleteBtn
                    propertiesTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                    ]}
                />
            )}
            <div className="mt-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <InsightContainer disableHeader={true} disableTable={true} disableCorrelationTable={true} />
                </BindLogic>
            </div>
        </>
    )
}
