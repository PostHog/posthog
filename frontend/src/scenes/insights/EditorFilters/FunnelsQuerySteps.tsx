import './FunnelsQuerySteps.scss'

import { useActions, useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { EditorFilterProps, FilterType, FunnelVizType as FunnelVizTypeEnum } from '~/types'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { AggregationSelect } from '../filters/AggregationSelect'
import { FunnelConversionWindowFilter } from '../views/Funnels/FunnelConversionWindowFilter'
import { FunnelVizType } from '../views/Funnels/FunnelVizType'
import { FunnelDataWarehouseStepDefinitionPopover } from './FunnelDataWarehouseStepDefinitionPopover'

export const FUNNEL_STEP_COUNT_LIMIT = 30

export function FunnelsQuerySteps({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { series, querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const supportsDwhFunnels = featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DWH_FUNNEL_SUPPORT]
    const isFunnelDwhStepPopoverVariant =
        supportsDwhFunnels && featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DWH_FUNNEL_STEP_UI] === 'popover'

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

    const { groupsTaxonomicTypes, showGroupsOptions } = useValues(groupsModel)

    if (!actionFilters) {
        return null
    }

    const filterSteps = series || []
    const showSeriesIndicator = (series || []).length > 0

    // TODO: Sort out title offset
    return (
        <>
            <div className="flex justify-between items-center">
                <LemonLabel>Query Steps</LemonLabel>

                {(querySource as FunnelsQuery)?.funnelsFilter?.funnelVizType !== FunnelVizTypeEnum.Flow && (
                    <Tooltip docLink="https://posthog.com/docs/product-analytics/funnels#graph-type">
                        <div className="flex items-center gap-2">
                            <span className="text-secondary">Graph type</span>
                            <FunnelVizType insightProps={insightProps} />
                        </div>
                    </Tooltip>
                )}
            </div>
            <div className="FunnelsQuerySteps">
                <ActionFilter
                    bordered
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
                        ...(supportsDwhFunnels ? [TaxonomicFilterGroupType.DataWarehouse] : []),
                    ]}
                    definitionPopoverRenderer={
                        isFunnelDwhStepPopoverVariant ? FunnelDataWarehouseStepDefinitionPopover : undefined
                    }
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
            <div className="mt-4 deprecated-space-y-4">
                {showGroupsOptions && (
                    <div className="flex items-center w-full gap-2" data-attr="funnel-aggregation-filter">
                        <span>Aggregating by</span>
                        <AggregationSelect insightProps={insightProps} hogqlAvailable />
                    </div>
                )}

                <FunnelConversionWindowFilter insightProps={insightProps} />
            </div>
        </>
    )
}
