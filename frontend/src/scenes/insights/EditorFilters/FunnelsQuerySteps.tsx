import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { EditorFilterProps } from '~/types'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ToggleButtonChartFilter } from '../views/Funnels/ToggleButtonChartFilter'
import { funnelCommandLogic } from '../views/Funnels/funnelCommandLogic'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { EditorFilterItemTitle } from './EditorFilterItemTitle'
import { AggregationSelect } from '../filters/AggregationSelect'
import { FunnelConversionWindowFilter } from '../views/Funnels/FunnelConversionWindowFilter'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element {
    const { isStepsEmpty, filterSteps, filters } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    useMountedLogic(funnelCommandLogic)

    // TODO: Sort out title offset
    return (
        <>
            <div className="mb-05 flex justify-between items-center">
                <EditorFilterItemTitle label={'Query Steps'} />

                <div className="flex items-center">
                    <span
                        style={{
                            marginRight: 6,
                            textTransform: 'none',
                            fontWeight: 'normal',
                            color: 'var(--muted)',
                        }}
                    >
                        Graph type
                    </span>
                    <ToggleButtonChartFilter simpleMode />
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
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                ]}
            />
            <div className="mb-05" />

            <div className="mt space-y">
                {showGroupsOptions && (
                    <div className="flex items-center full-width">
                        <span className="text-muted mr-05">Aggregating by </span>
                        <AggregationSelect
                            aggregationGroupTypeIndex={filters.aggregation_group_type_index}
                            onChange={(newValue) => setFilters({ aggregation_group_type_index: newValue })}
                        />
                    </div>
                )}
                <FunnelConversionWindowFilter horizontal />
            </div>
        </>
    )
}
