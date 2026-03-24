import { useActions, useValues } from 'kea'

import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS, SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { alphabet } from 'lib/utils'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { groupsModel } from '~/models/groupsModel'
import { FunnelsQuery, LifecycleQuery, NodeKind, StickinessQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { ChartDisplayType, FilterType } from '~/types'

import { actionsAndEventsToSeries } from '../InsightQuery/utils/filtersToQueryNode'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { LifecycleSeriesHeader } from './LifecycleSeriesHeader'

const lifecycleDataWarehousePopoverFields: DataWarehousePopoverField[] = [
    { key: 'timestamp_field', label: 'Timestamp', allowHogQL: true },
    { key: 'created_at_field', label: 'Created at', allowHogQL: true },
    { key: 'aggregation_target_field', label: 'Aggregation target', allowHogQL: true },
]

export function TrendsSeries(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource, isTrends, isLifecycle, isStickiness, display, hasFormula, series } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const supportsDwhLifecycle = featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DWH_LIFECYCLE_SUPPORT]

    const { hasPageview, hasScreen } = getProjectEventExistence()

    const propertiesTaxonomicGroupTypes = getInsightPropertyFilterGroupTypes({
        groupsTaxonomicTypes,
        hasPageview,
        hasScreen,
        includeDataWarehouseProperties: true,
    })

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const filters = queryNodeToFilter(querySource)
    const isFunnels = querySource.kind === NodeKind.FunnelsQuery
    const mathAvailability = isLifecycle
        ? MathAvailability.None
        : isStickiness
          ? MathAvailability.ActorsOnly
          : display === ChartDisplayType.CalendarHeatmap
            ? MathAvailability.CalendarHeatmapOnly
            : display === ChartDisplayType.BoxPlot
              ? MathAvailability.BoxPlotOnly
              : MathAvailability.All

    return (
        <>
            {isLifecycle && <LifecycleSeriesHeader />}
            <ActionFilter
                filters={filters}
                setFilters={(payload: Partial<FilterType>): void => {
                    if (isLifecycle) {
                        updateQuerySource({
                            series: actionsAndEventsToSeries(
                                payload as any,
                                true,
                                mathAvailability,
                                NodeKind.LifecycleDataWarehouseNode
                            ),
                        } as LifecycleQuery)
                    } else if (isFunnels) {
                        updateQuerySource({
                            series: actionsAndEventsToSeries(
                                payload as any,
                                true,
                                mathAvailability,
                                NodeKind.FunnelsDataWarehouseNode
                            ),
                        } as FunnelsQuery)
                    } else {
                        updateQuerySource({
                            series: actionsAndEventsToSeries(
                                payload as any,
                                true,
                                mathAvailability,
                                NodeKind.DataWarehouseNode
                            ),
                        } as TrendsQuery | StickinessQuery)
                    }
                }}
                typeKey={keyForInsightLogicProps('new')(insightProps)}
                buttonCopy={`Add graph ${hasFormula ? 'variable' : 'series'}`}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (display && SINGLE_SERIES_DISPLAY_TYPES.includes(display) && !hasFormula) || isLifecycle
                        ? 1
                        : alphabet.length
                }
                mathAvailability={mathAvailability}
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                actionsTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    ...(hasPageview ? [TaxonomicFilterGroupType.PageviewEvents] : []),
                    ...(hasScreen ? [TaxonomicFilterGroupType.ScreenEvents] : []),
                    TaxonomicFilterGroupType.AutocaptureEvents,
                    ...((isTrends &&
                        display !== ChartDisplayType.CalendarHeatmap &&
                        display !== ChartDisplayType.BoxPlot) ||
                    (supportsDwhLifecycle && isLifecycle)
                        ? [TaxonomicFilterGroupType.DataWarehouse]
                        : []),
                ]}
                hideDeleteBtn={series?.length === 1}
                addFilterDocLink="https://posthog.com/docs/product-analytics/trends/filters"
                dataWarehousePopoverFields={isLifecycle ? lifecycleDataWarehousePopoverFields : undefined}
            />
        </>
    )
}
