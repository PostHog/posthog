import { BindLogic, useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType, InsightShortId, InsightType } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { Query } from '~/queries/Query/Query'
import { FunnelsQuery, InsightQueryNode, TrendsQuery } from '~/queries/schema'

import './Experiment.scss'

export interface MetricSelectorProps {
    dashboardItemId: InsightShortId
    setPreviewInsight: (filters?: Partial<FilterType>) => void
}

export function MetricSelector({ dashboardItemId, setPreviewInsight }: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({ dashboardItemId, syncWithUrl: false })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { isTrends, series, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    // calculated properties
    const filterSteps = series || []
    const isStepsEmpty = filterSteps.length === 0

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    value={isTrends ? InsightType.TRENDS : InsightType.FUNNELS}
                    onChange={(val) => {
                        val && setPreviewInsight({ insight: val })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>

            <div>
                <SamplingFilter
                    insightProps={insightProps}
                    infoTooltipContent="Sampling on experiment goals is an Alpha feature to enable faster computation of experiment results."
                />
                <br />
            </div>

            <ActionFilter
                bordered
                filters={queryNodeToFilter(querySource as InsightQueryNode)}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as
                        | TrendsQuery
                        | FunnelsQuery)
                }}
                typeKey={`experiment-${isTrends ? InsightType.TRENDS : InsightType.FUNNELS}-secondary-metric`}
                mathAvailability={isTrends ? undefined : MathAvailability.None}
                hideDeleteBtn={isTrends || filterSteps.length === 1}
                buttonCopy={isTrends ? 'Add graph series' : 'Add funnel step'}
                showSeriesIndicator={isTrends || !isStepsEmpty}
                entitiesLimit={isTrends ? 1 : undefined}
                seriesIndicatorType={isTrends ? undefined : 'numeric'}
                sortable={isTrends ? undefined : true}
                showNestedArrow={isTrends ? undefined : true}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
            />

            <div className="mt-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <Query query={query} context={{ insightProps }} readOnly />
                </BindLogic>
            </div>
        </>
    )
}
