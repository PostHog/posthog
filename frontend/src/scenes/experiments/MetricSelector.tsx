import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect } from 'react'
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
import { InsightTestAccountFilter } from '~/queries/nodes/InsightViz/filters/InsightTestAccountFilter'
import { Query } from '~/queries/Query/Query'
import { FunnelsQuery, InsightQueryNode, TrendsQuery } from '~/queries/schema'
import { EditorFilterProps, FilterType, InsightLogicProps, InsightShortId, InsightType } from '~/types'

export interface MetricSelectorProps {
    dashboardItemId: InsightShortId
    setPreviewInsight: (filters?: Partial<FilterType>) => void
    showDateRangeBanner?: boolean
    forceTrendExposureMetric?: boolean
}

export function MetricSelector({
    dashboardItemId,
    setPreviewInsight,
    showDateRangeBanner,
    forceTrendExposureMetric,
}: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({ dashboardItemId, syncWithUrl: false })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query } = useValues(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { isTrends } = useValues(insightVizDataLogic(insightProps))

    useEffect(() => {
        if (forceTrendExposureMetric && !isTrends) {
            setPreviewInsight({ insight: InsightType.TRENDS })
        }
    }, [forceTrendExposureMetric, isTrends])

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
                    disabledReason={forceTrendExposureMetric ? 'Exposure metric can only be a trend graph' : undefined}
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
                    Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can cause a
                    mismatch between the preview and the actual results.
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
                <InsightTestAccountFilter query={querySource as InsightQueryNode} setQuery={updateQuerySource} />
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
                    closeDelayMs={200}
                    title={
                        <div className="space-y-2">
                            <div>
                                When breaking down funnels, it's possible that the same properties don't exist on every
                                event. For example, if you want to break down by browser on a funnel that contains both
                                frontend and backend events.
                            </div>
                            <div>
                                In this case, you can choose from which step the properties should be selected from by
                                modifying the attribution type. There are four modes to choose from:
                            </div>
                            <ul className="list-disc pl-4">
                                <li>First touchpoint: the first property value seen in any of the steps is chosen.</li>
                                <li>Last touchpoint: the last property value seen from all steps is chosen.</li>
                                <li>
                                    All steps: the property value must be seen in all steps to be considered in the
                                    funnel.
                                </li>
                                <li>Specific step: only the property value seen at the selected step is chosen.</li>
                            </ul>
                            <div>
                                Read more in the{' '}
                                <Link to="https://posthog.com/docs/product-analytics/funnels#attribution-types">
                                    documentation.
                                </Link>
                            </div>
                        </div>
                    }
                >
                    <IconInfo className="text-xl text-muted-alt shrink-0 ml-1" />
                </Tooltip>
            </div>
            <Attribution insightProps={insightProps} />
        </div>
    )
}
