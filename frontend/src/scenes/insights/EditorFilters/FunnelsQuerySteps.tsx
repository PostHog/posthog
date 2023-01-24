import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { groupsModel } from '~/models/groupsModel'

import { EditorFilterProps, FilterType, FunnelsFilterType, InsightLogicProps, QueryEditorFilterProps } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { FunnelVizType, FunnelVizTypeDataExploration } from '../views/Funnels/FunnelVizType'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { AggregationSelect } from '../filters/AggregationSelect'
import {
    FunnelConversionWindowFilter,
    FunnelConversionWindowFilterDataExploration,
} from '../views/Funnels/FunnelConversionWindowFilter'
import { insightDataLogic } from '../insightDataLogic'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { FunnelsQuery } from '~/queries/schema'
import { isStepsEmpty } from 'scenes/funnels/funnelUtils'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelsQueryStepsDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, querySource } = useValues(insightDataLogic(insightProps))
    const { updateInsightFilter, updateQuerySource } = useActions(insightDataLogic(insightProps))

    const filters = queryNodeToFilter(querySource)
    const setFilters = (payload: Partial<FilterType>): void => {
        updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as FunnelsQuery)
    }

    return (
        <FunnelsQueryStepsComponent
            filters={filters}
            setFilters={setFilters}
            filterSteps={(querySource as FunnelsQuery).series}
            insightProps={insightProps}
            isDataExploration
        />
    )
}

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element {
    const { filterSteps, filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <FunnelsQueryStepsComponent
            filters={filters}
            setFilters={setFilters}
            filterSteps={filterSteps}
            insightProps={insightProps}
            isDataExploration={false}
        />
    )
}

type FunnelsQueryStepsComponentProps = {
    filters: Partial<FunnelsFilterType>
    setFilters: (filters: Partial<FunnelsFilterType>) => void
    filterSteps: Record<string, any>[]
    isDataExploration: boolean
    insightProps: InsightLogicProps
}

export function FunnelsQueryStepsComponent({
    filters,
    setFilters,
    filterSteps,
    isDataExploration,
    insightProps,
}: FunnelsQueryStepsComponentProps): JSX.Element {
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)

    // TODO: Sort out title offset
    return (
        <>
            <div className="flex justify-between items-center">
                <LemonLabel>Query Steps</LemonLabel>

                <div className="flex items-center gap-2">
                    <span className="text-muted">Graph type</span>
                    {isDataExploration ? (
                        <FunnelVizTypeDataExploration insightProps={insightProps} />
                    ) : (
                        <FunnelVizType insightProps={insightProps} />
                    )}
                </div>
            </div>

            <ActionFilter
                bordered
                filters={filters}
                setFilters={setFilters}
                typeKey={`EditFunnel-action`}
                mathAvailability={MathAvailability.None}
                hideDeleteBtn={filterSteps.length === 1}
                buttonCopy="Add step"
                showSeriesIndicator={!isStepsEmpty(filters)}
                seriesIndicatorType="numeric"
                entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
                sortable
                showNestedArrow={true}
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
            />
            <div className="mt-4 space-y-4">
                {showGroupsOptions && (
                    <div className="flex items-center w-full gap-2">
                        <span>Aggregating by</span>
                        <AggregationSelect
                            aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                            onChange={(newValue) => setFilters({ aggregation_group_type_index: newValue })}
                        />
                    </div>
                )}
                {isDataExploration ? (
                    <FunnelConversionWindowFilterDataExploration insightProps={insightProps} />
                ) : (
                    <FunnelConversionWindowFilter insightProps={insightProps} />
                )}
            </div>
        </>
    )
}
