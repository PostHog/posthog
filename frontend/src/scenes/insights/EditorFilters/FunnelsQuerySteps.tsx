import './FunnelsQuerySteps.scss'

import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { groupsModel } from '~/models/groupsModel'
import { actionsAndEventsToSeries } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { EditorFilterProps, FilterType } from '~/types'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { FunnelDataWarehouseStepDefinitionPopover } from './FunnelDataWarehouseStepDefinitionPopover'

export const FUNNEL_STEP_COUNT_LIMIT = 30

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { series, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { hasPageview, hasScreen } = getProjectEventExistence()

    const actionFilters = isInsightQueryNode(querySource) ? queryNodeToFilter(querySource) : null
    const setActionFilters = (payload: Partial<FilterType>): void => {
        updateQuerySource({
            series: actionsAndEventsToSeries(
                payload as any,
                true,
                MathAvailability.FunnelsOnly,
                NodeKind.FunnelsDataWarehouseNode
            ),
        } as FunnelsQuery)
    }

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    if (!actionFilters) {
        return null
    }

    const filterSteps = series || []
    const showSeriesIndicator = (series || []).length > 0

    // TODO: Sort out title offset
    return (
        <>
            <div className="FunnelsQuerySteps">
                <ActionFilter
                    bordered={false}
                    filters={actionFilters}
                    setFilters={setActionFilters}
                    typeKey={keyForInsightLogicProps('new')(insightProps)}
                    mathAvailability={MathAvailability.FunnelsOnly}
                    hideDeleteBtn={filterSteps.length === 1}
                    buttonCopy="Add step"
                    showSeriesIndicator={showSeriesIndicator}
                    seriesIndicatorType="numeric"
                    entitiesLimit={FUNNEL_STEP_COUNT_LIMIT}
                    sortable
                    showNestedArrow
                    propertiesTaxonomicGroupTypes={getInsightPropertyFilterGroupTypes({
                        groupsTaxonomicTypes,
                        hasPageview,
                        hasScreen,
                    })}
                    addFilterDocLink="https://posthog.com/docs/product-analytics/trends/filters"
                    actionsTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        ...(hasPageview ? [TaxonomicFilterGroupType.PageviewEvents] : []),
                        ...(hasScreen ? [TaxonomicFilterGroupType.ScreenEvents] : []),
                        TaxonomicFilterGroupType.AutocaptureEvents,
                        TaxonomicFilterGroupType.DataWarehouse,
                    ]}
                    definitionPopoverRenderer={FunnelDataWarehouseStepDefinitionPopover}
                    dataWarehousePopoverFields={[
                        {
                            key: 'id_field',
                            label: 'Unique ID',
                        },
                        {
                            key: 'timestamp_field',
                            label: 'Timestamp',
                        },
                        {
                            key: 'aggregation_target_field',
                            label: 'Aggregation target',
                            allowHogQL: true,
                        },
                    ]}
                />
            </div>
        </>
    )
}
