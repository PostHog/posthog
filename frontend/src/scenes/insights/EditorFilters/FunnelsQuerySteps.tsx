import { useValues, useActions, useMountedLogic } from 'kea'

import { groupsModel, Noun } from '~/models/groupsModel'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'

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
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { FunnelsQuery } from '~/queries/schema'
import { isStepsEmpty } from 'scenes/funnels/funnelUtils'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelsQueryStepsDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter, querySource, aggregationTargetLabel } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter, updateQuerySource } = useActions(funnelDataLogic(insightProps))
    // TODO: Replicate command logic
    // useMountedLogic(funnelCommandLogic)

    const actionFilters = queryNodeToFilter(querySource)
    const setActionFilters = (payload: Partial<FilterType>): void => {
        updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as FunnelsQuery)
    }

    return (
        <FunnelsQueryStepsComponent
            querySource={querySource}
            updateQuerySource={updateQuerySource}
            filters={insightFilter as Partial<FunnelsFilterType>}
            actionFilters={actionFilters}
            setFilters={updateInsightFilter}
            setActionFilters={setActionFilters}
            filterSteps={(querySource as FunnelsQuery).series}
            aggregationTargetLabel={aggregationTargetLabel}
            showSeriesIndicator={(querySource as FunnelsQuery).series.length > 0}
            isDataExploration
            insightProps={insightProps}
        />
    )
}

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element {
    const { filterSteps, filters, aggregationTargetLabel } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    useMountedLogic(funnelCommandLogic)

    return (
        <FunnelsQueryStepsComponent
            querySource={filters}
            updateQuerySource={setFilters}
            filters={filters}
            setFilters={setFilters}
            actionFilters={filters}
            setActionFilters={setFilters}
            filterSteps={filterSteps}
            aggregationTargetLabel={aggregationTargetLabel}
            showSeriesIndicator={!isStepsEmpty(filters)}
            insightProps={insightProps}
        />
    )
}

type FunnelsQueryStepsComponentProps = {
    querySource: Pick<FunnelsQuery, 'aggregation_group_type_index'>
    updateQuerySource: (querySource: Pick<FunnelsQuery, 'aggregation_group_type_index'>) => void
    filters: Partial<FunnelsFilterType>
    setFilters: (filters: Partial<FunnelsFilterType>) => void
    actionFilters: Partial<FunnelsFilterType>
    setActionFilters: (filters: Partial<FunnelsFilterType>) => void
    filterSteps: Record<string, any>[]
    aggregationTargetLabel: Noun
    showSeriesIndicator: boolean
    isDataExploration?: boolean
    insightProps: InsightLogicProps
}

export function FunnelsQueryStepsComponent({
    querySource,
    updateQuerySource,
    filters,
    setFilters,
    actionFilters,
    setActionFilters,
    filterSteps,
    aggregationTargetLabel,
    showSeriesIndicator,
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
                filters={actionFilters}
                setFilters={setActionFilters}
                typeKey={`EditFunnel-action`}
                mathAvailability={MathAvailability.None}
                hideDeleteBtn={filterSteps.length === 1}
                buttonCopy="Add step"
                showSeriesIndicator={showSeriesIndicator}
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
                            aggregationGroupTypeIndex={querySource.aggregation_group_type_index}
                            onChange={(newValue) => updateQuerySource({ aggregation_group_type_index: newValue })}
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
