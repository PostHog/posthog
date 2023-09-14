import { useValues, useActions } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'

import { FilterType, EditorFilterProps } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { FunnelVizType } from '../views/Funnels/FunnelVizType'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { AggregationSelect } from '../filters/AggregationSelect'
import { FunnelConversionWindowFilter } from '../views/Funnels/FunnelConversionWindowFilter'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { FunnelsQuery } from '~/queries/schema'
import { isInsightQueryNode } from '~/queries/utils'

export const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { querySource, series } = useValues(funnelDataLogic(insightProps))
    const { updateQuerySource } = useActions(funnelDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const actionFilters = queryNodeToFilter(querySource)
    const setActionFilters = (payload: Partial<FilterType>): void => {
        updateQuerySource({ series: actionsAndEventsToSeries(payload as any) } as FunnelsQuery)
    }

    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)

    const filterSteps = series || []
    const showSeriesIndicator = (series || []).length > 0

    // TODO: Sort out title offset
    return (
        <>
            <div className="flex justify-between items-center">
                <LemonLabel>Query Steps</LemonLabel>

                <div className="flex items-center gap-2">
                    <span className="text-muted">Graph type</span>
                    <FunnelVizType insightProps={insightProps} />
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
                showNestedArrow
                propertiesTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]}
            />
            <div className="mt-4 space-y-4">
                {showGroupsOptions && (
                    <div className="flex items-center w-full gap-2">
                        <span>Aggregating by</span>
                        <AggregationSelect insightProps={insightProps} hogqlAvailable />
                    </div>
                )}

                <FunnelConversionWindowFilter insightProps={insightProps} />
            </div>
        </>
    )
}
