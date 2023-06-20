import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { FilterType, FunnelVizType, InsightShortId, InsightType } from '~/types'
import './Experiment.scss'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { samplingFilterLogic } from 'scenes/insights/EditorFilters/samplingFilterLogic'
import { Query } from '~/queries/Query/Query'
import { FunnelsQuery, InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema'
import { actionsAndEventsToSeries, filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { useEffect } from 'react'
import { secondaryMetricsFilterLogic } from './secondaryMetricsFiltersLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import equal from 'fast-deep-equal'
import { FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { DEFAULT_DURATION } from './secondaryMetricsLogic'

export interface MetricSelectorProps {
    insightId: string
    createPreviewInsight: (filters?: Partial<FilterType>) => void
    setFilters: (filters: Partial<FilterType>) => void
    previewInsightId: InsightShortId | null
    filters: Partial<FilterType>
}

export function MetricSelector({
    insightId,
    createPreviewInsight,
    previewInsightId,
    filters,
    setFilters,
}: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId as InsightShortId,
        syncWithUrl: false,
        // disableDataExploration: true,
    })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { internalQuery } = useValues(insightDataLogic(insightProps))
    const { setQuery } = useActions(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { series, isTrends, isFunnels, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    // set the initial query from filters
    useEffect(() => {
        if (internalQuery === null) {
            console.debug('SETQUERY')
            const query: InsightVizNode = {
                kind: NodeKind.InsightVizNode,
                source: filtersToQueryNode(filters),
            }
            setQuery(query)
        }
    }, [filters])

    // update filters when query changes
    useEffect(() => {
        const filtersFromQuery = querySource ? queryNodeToFilter(querySource) : filters
        if (!equal(filters, filtersFromQuery)) {
            console.group('SETFILTERS')
            console.debug('filtersFromQuery: ', filtersFromQuery)
            console.debug('filters: ', filters)
            console.groupEnd()
            setFilters(filtersFromQuery)
        }
    }, [querySource])

    // calculated properties
    const filterSteps = series || []
    const isStepsEmpty = filterSteps.length === 0

    // const { samplingAvailable } = useValues(samplingFilterLogic({ insightType: experimentInsightType, insightProps }))

    // console.debug('isTrends: ', isTrends)
    // console.debug('isFunnels: ', isFunnels)

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    value={isTrends ? InsightType.TRENDS : InsightType.FUNNELS}
                    onChange={(val) => {
                        console.debug('VAL', val, val === InsightType.FUNNELS)
                        let newInsightFilters
                        if (val === InsightType.FUNNELS) {
                            console.debug('A')
                            newInsightFilters = cleanFilters({
                                insight: InsightType.FUNNELS,
                                funnel_viz_type: FunnelVizType.Steps,
                                date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                                layout: FunnelLayout.horizontal,
                                // ...filters,
                            })
                        } else {
                            console.debug('B')
                            newInsightFilters = cleanFilters({
                                insight: InsightType.TRENDS,
                                date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                                // ...filters,
                            })
                        }
                        console.debug('setting new insight filters', newInsightFilters)
                        updateQuerySource(filtersToQueryNode(newInsightFilters))
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {/* {samplingAvailable ? (
                <div>
                    <SamplingFilter
                        insightProps={insightProps}
                        infoTooltipContent="Sampling on experiment goals is an Alpha feature to enable faster computation of experiment results."
                        setFilters={(payload) =>
                            setFilters({
                                ...filters,
                                ...(payload.sampling_factor
                                    ? { sampling_factor: payload.sampling_factor }
                                    : { sampling_factor: null }),
                            })
                        }
                        initialSamplingPercentage={filters.sampling_factor ? filters.sampling_factor * 100 : null}
                    />
                    <br />
                </div>
            ) : null} */}

            <ActionFilter
                bordered
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as FunnelsQuery)
                }}
                typeKey={`experiment-funnel-goal-${JSON.stringify(filters)}`}
                mathAvailability={isFunnels ? MathAvailability.None : undefined}
                hideDeleteBtn={isTrends || filterSteps.length === 1}
                buttonCopy={isTrends ? 'Add graph series' : 'Add funnel step'}
                showSeriesIndicator={isTrends || !isStepsEmpty}
                seriesIndicatorType="numeric"
                sortable={isFunnels}
                showNestedArrow={true}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
                entitiesLimit={isTrends ? 1 : undefined}
            />
            <div className="mt-4">
                <BindLogic logic={insightLogic} props={insightProps}>
                    <BindLogic logic={trendsLogic} props={insightProps}>
                        <Query query={{ ...query, showLastComputation: true }} context={{ insightProps }} readOnly />
                    </BindLogic>
                </BindLogic>
                <pre>{JSON.stringify(query, null, 2)}</pre>
            </div>
        </>
    )
}
