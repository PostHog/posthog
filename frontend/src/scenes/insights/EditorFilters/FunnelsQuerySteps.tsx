import { useValues, useActions, useMountedLogic } from 'kea'

import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightDataLogic } from '../insightDataLogic'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { groupsModel } from '~/models/groupsModel'

import { EditorFilterProps, FunnelsFilterType } from '~/types'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { ToggleButtonChartFilter } from '../views/Funnels/ToggleButtonChartFilter'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { AggregationSelect } from '../filters/AggregationSelect'
import { FunnelConversionWindowFilter } from '../views/Funnels/FunnelConversionWindowFilter'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelsQueryStepsDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { insightFilter } = useValues(insightDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightDataLogic(insightProps))

    return (
        <div className="flex justify-between items-center">
            <LemonLabel>Query Steps</LemonLabel>

            <div className="flex items-center gap-2">
                <span className="text-muted">Graph type</span>
                <ToggleButtonChartFilter {...insightFilter} setFilter={updateInsightFilter} />
            </div>
        </div>
    )
}

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element {
    const { isStepsEmpty, filterSteps, filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    useMountedLogic(funnelCommandLogic)

    // TODO: Sort out title offset
    return (
        <>
            <div className="flex justify-between items-center">
                <LemonLabel>Query Steps</LemonLabel>

                <div className="flex items-center gap-2">
                    <span className="text-muted">Graph type</span>
                    <ToggleButtonChartFilter
                        {...filters}
                        setFilter={(filter: FunnelsFilterType) => setFilters({ ...filters, ...filter })}
                    />
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
                showSeriesIndicator={!isStepsEmpty}
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
                <FunnelConversionWindowFilter />
            </div>
        </>
    )
}
