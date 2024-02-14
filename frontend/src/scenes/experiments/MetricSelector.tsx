import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Attribution } from 'scenes/insights/EditorFilters/AttributionFilter'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelConversionWindowFilter } from 'scenes/insights/views/Funnels/FunnelConversionWindowFilter'

import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { TestAccountFilter } from '~/queries/nodes/InsightViz/filters/TestAccountFilter'
import { Query } from '~/queries/Query/Query'
import { FunnelsQuery, InsightQueryNode, TrendsQuery } from '~/queries/schema'
import { EditorFilterProps, FilterType, InsightLogicProps, InsightShortId, InsightType } from '~/types'

import { DEFAULT_DURATION } from './experimentLogic'

export interface MetricSelectorProps {
    dashboardItemId: InsightShortId
    setPreviewInsight: (filters?: Partial<FilterType>) => void
    showDateRangeBanner?: boolean
}

export function MetricSelector({
    dashboardItemId,
    setPreviewInsight,
    showDateRangeBanner,
}: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({ dashboardItemId, syncWithUrl: false })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { isTrends } = useValues(insightVizDataLogic(insightProps))

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    data-attr="metrics-selector"
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

            <ExperimentInsightCreator insightProps={insightProps} />

            {showDateRangeBanner && (
                <LemonBanner type="info" className="mt-3 mb-3">
                    Preview insights are generated based on {DEFAULT_DURATION} days of data. This can cause a mismatch
                    between the preview and the actual results.
                </LemonBanner>
            )}

            <div className="mt-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <Query query={query} context={{ insightProps }} readOnly />
                </BindLogic>
            </div>
        </>
    )
}

export function ExperimentInsightCreator({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    // insightVizDataLogic
    const { isTrends, series, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    // calculated properties
    const filterSteps = series || []
    const isStepsEmpty = filterSteps.length === 0

    return (
        <>
            <ActionFilter
                bordered
                filters={queryNodeToFilter(querySource as InsightQueryNode)}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({
                        series: actionsAndEventsToSeries(
                            payload as any,
                            true,
                            isTrends ? MathAvailability.All : MathAvailability.None
                        ),
                    } as TrendsQuery | FunnelsQuery)
                }}
                typeKey={`experiment-${isTrends ? InsightType.TRENDS : InsightType.FUNNELS}-${
                    insightProps.dashboardItemId
                }-metric`}
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
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
            />
            <div className="mt-4 space-y-4">
                {!isTrends && (
                    <>
                        <div className="flex items-center w-full gap-2">
                            <span>Aggregating by</span>
                            <AggregationSelect insightProps={insightProps} hogqlAvailable />
                        </div>
                        <FunnelConversionWindowFilter insightProps={insightProps} />
                        <AttributionSelect insightProps={insightProps} />
                    </>
                )}
                <TestAccountFilter query={querySource as InsightQueryNode} setQuery={updateQuerySource} />
            </div>
        </>
    )
}

export function AttributionSelect({ insightProps }: EditorFilterProps): JSX.Element {
    return (
        <div className="flex items-center w-full gap-2">
            <div className="flex">
                <span>Attribution type</span>
                <Tooltip
                    title={
                        <div>
                            When breaking funnels down by a property, you can choose how to assign users to the various
                            property values. This is useful because property values can change for a user/group as
                            someone travels through the funnel.
                            <ul className="list-disc pl-4 pt-4">
                                <li>First step: the first property value seen from all steps is chosen.</li>
                                <li>Last step: last property value seen from all steps is chosen.</li>
                                <li>Specific step: the property value seen at that specific step is chosen.</li>
                                <li>All steps: the property value must be seen in all steps.</li>
                                <li>Any step: the property value must be seen on at least one step of the funnel.</li>
                            </ul>
                        </div>
                    }
                >
                    <span>
                        <IconInfo className="w-4 info-indicator" />
                    </span>
                </Tooltip>
            </div>
            <Attribution insightProps={insightProps} />
        </div>
    )
}
