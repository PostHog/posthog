import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { DataWarehousePopoverField, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DISPLAY_TYPES_TO_CATEGORIES, SINGLE_SERIES_DISPLAY_TYPES } from 'lib/constants'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import { alphabet } from 'lib/utils/strings'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getInsightPropertyFilterGroupTypes } from 'scenes/insights/utils/propertyTaxonomicGroupTypes'

import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { ChartDisplayType, InsightType } from '~/types'

import { LifecycleSeriesHeader } from 'products/product_analytics/frontend/insights/lifecycle/LifecycleSeriesHeader'
import { TrendsFormula } from 'products/product_analytics/frontend/insights/trends/filters/TrendsFormula'

const lifecycleDataWarehousePopoverFields: DataWarehousePopoverField[] = [
    { key: 'timestamp_field', label: 'Timestamp', allowHogQL: true },
    { key: 'created_at_field', label: 'Created at', allowHogQL: true },
    { key: 'aggregation_target_field', label: 'Aggregation target', allowHogQL: true },
]

export function TrendsSeries(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const {
        querySource,
        isTrends,
        isLifecycle,
        isStickiness,
        display,
        hasFormula,
        series,
        isBreakdownSeries,
        seriesMathAvailability,
    } = useValues(insightVizDataLogic(insightProps))
    const { updateSeries, setFormulaMode } = useActions(insightVizDataLogic(insightProps))

    const { groupsTaxonomicTypes } = useValues(groupsModel)

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

    const supportsDataWarehouse =
        (isTrends && display !== ChartDisplayType.CalendarHeatmap) || isLifecycle || isStickiness

    const showFormulaOption =
        isTrends && display !== ChartDisplayType.CalendarHeatmap && display !== ChartDisplayType.BoxPlot

    const canDisableFormula: boolean =
        !isTrends || !display || !SINGLE_SERIES_DISPLAY_TYPES.includes(display) || series?.length === 1

    const formulaFooter = showFormulaOption ? (
        <LemonSwitch
            className="mt-2"
            checked={hasFormula}
            onChange={setFormulaMode}
            disabled={hasFormula && !canDisableFormula}
            label="Formula mode"
            bordered
            id="trends-formula-switch"
            data-attr="trends-formula-switch"
        />
    ) : null

    return (
        <>
            {isLifecycle && <LifecycleSeriesHeader />}
            <SeriesActionFilter
                allowBehavioralPropertyFilter
                series={series ?? []}
                onChange={updateSeries}
                insightType={
                    isLifecycle ? InsightType.LIFECYCLE : isStickiness ? InsightType.STICKINESS : InsightType.TRENDS
                }
                hasBreakdown={isBreakdownSeries}
                trendsDisplayCategory={
                    isTrends ? DISPLAY_TYPES_TO_CATEGORIES[display || ChartDisplayType.ActionsLineGraph] : null
                }
                dataWarehouseNodeKind={isLifecycle ? NodeKind.LifecycleDataWarehouseNode : NodeKind.DataWarehouseNode}
                typeKey={keyForInsightLogicProps('new')(insightProps)}
                buttonCopy={hasFormula ? 'Variable' : 'Series'}
                showSeriesIndicator
                showNestedArrow
                entitiesLimit={
                    (display && SINGLE_SERIES_DISPLAY_TYPES.includes(display) && !hasFormula) || isLifecycle
                        ? 1
                        : alphabet.length
                }
                mathAvailability={seriesMathAvailability}
                propertiesTaxonomicGroupTypes={propertiesTaxonomicGroupTypes}
                actionsTaxonomicGroupTypes={[
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    ...(hasPageview ? [TaxonomicFilterGroupType.PageviewEvents] : []),
                    ...(hasScreen ? [TaxonomicFilterGroupType.ScreenEvents] : []),
                    TaxonomicFilterGroupType.AutocaptureEvents,
                    ...(supportsDataWarehouse ? [TaxonomicFilterGroupType.DataWarehouse] : []),
                ]}
                flagCallsFromFlagEvaluations={supportsDataWarehouse}
                hideDeleteBtn={series?.length === 1}
                addFilterDocLink="https://posthog.com/docs/product-analytics/trends/filters"
                dataWarehousePopoverFields={isLifecycle ? lifecycleDataWarehousePopoverFields : undefined}
                customFooter={formulaFooter}
            />
            {hasFormula && <TrendsFormula insightProps={insightProps} />}
        </>
    )
}
