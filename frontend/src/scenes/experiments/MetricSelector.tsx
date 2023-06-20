import { useEffect } from 'react'
import equal from 'fast-deep-equal'
import { BindLogic, useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'

import { DEFAULT_DURATION } from './secondaryMetricsLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsLogic } from 'scenes/trends/trendsLogic'

import { actionsAndEventsToSeries, filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { FilterType, FunnelVizType, InsightShortId, InsightType } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { LemonSelect } from '@posthog/lemon-ui'
import { SamplingFilter } from 'scenes/insights/EditorFilters/SamplingFilter'
import { Query } from '~/queries/Query/Query'
import { FunnelsQuery, InsightVizNode, NodeKind } from '~/queries/schema'
import { FunnelLayout } from 'lib/constants'

import './Experiment.scss'

export interface MetricSelectorProps {
    insightId: string
    setFilters: (filters: Partial<FilterType>) => void
    filters: Partial<FilterType>
}

export function MetricSelector({ insightId, filters, setFilters }: MetricSelectorProps): JSX.Element {
    // insightLogic
    const logic = insightLogic({ dashboardItemId: insightId as InsightShortId, syncWithUrl: false })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query, internalQuery } = useValues(insightDataLogic(insightProps))
    const { setQuery } = useActions(insightDataLogic(insightProps))

    // insightVizDataLogic
    const { series, isTrends, isFunnels, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    // set the initial query from filters
    useEffect(() => {
        if (internalQuery === null) {
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
            setFilters(filtersFromQuery)
        }
    }, [querySource])

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
                        let newInsightFilters
                        if (val === InsightType.FUNNELS) {
                            newInsightFilters = cleanFilters({
                                insight: InsightType.FUNNELS,
                                funnel_viz_type: FunnelVizType.Steps,
                                date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                                layout: FunnelLayout.horizontal,
                            })
                        } else {
                            newInsightFilters = cleanFilters({
                                insight: InsightType.TRENDS,
                                date_from: dayjs().subtract(DEFAULT_DURATION, 'day').format('YYYY-MM-DD'),
                                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                            })
                        }
                        updateQuerySource(filtersToQueryNode(newInsightFilters))
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
                        <Query
                            query={
                                {
                                    ...query,
                                    full: false,
                                    showLastComputation: true,
                                    showHeader: false,
                                    showTable: false,
                                    showCorrelationTable: false,
                                } as InsightVizNode
                            }
                            context={{ insightProps }}
                            readOnly
                        />
                    </BindLogic>
                </BindLogic>
                <pre>{JSON.stringify(query, null, 2)}</pre>
            </div>
        </>
    )
}
