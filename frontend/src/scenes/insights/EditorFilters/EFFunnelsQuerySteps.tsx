import React from 'react'
import { useValues, useActions, useMountedLogic } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from '../ActionFilter/ActionFilter'
import { EditorFilterProps } from '~/types'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { ToggleButtonChartFilter } from '../InsightTabs/FunnelTab/ToggleButtonChartFilter'
import { funnelCommandLogic } from '../InsightTabs/FunnelTab/funnelCommandLogic'
import { MathAvailability } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterRow'
import { EditorFilterItemTitle } from './EditorFilterItemTitle'
import { AggregationSelect } from '../AggregationSelect'
import { FunnelConversionWindowFilter } from '../InsightTabs/FunnelTab/FunnelConversionWindowFilter'

const FUNNEL_STEP_COUNT_LIMIT = 20

export function EFFunnelsQuerySteps({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { isStepsEmpty, filterSteps } = useValues(funnelLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))
    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)
    useMountedLogic(funnelCommandLogic)

    // TODO: Sort out title offset
    return (
        <>
            <div className="mb-05 space-between-items items-center">
                <EditorFilterItemTitle label={'Query Steps'} />

                <div className="flex-center">
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
                propertyFiltersPopover
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
                    <div className="flex-center full-width">
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
