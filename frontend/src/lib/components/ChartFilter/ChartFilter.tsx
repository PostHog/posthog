import { useActions, useValues } from 'kea'

import { IconGlobe, IconGraph, IconPieChart, IconRetentionHeatmap, IconTrends } from '@posthog/icons'
import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import {
    Icon123,
    IconAreaChart,
    IconCumulativeChart,
    IconDonutChart,
    IconTableChart,
    IconTrendingUp,
} from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isBoxPlotMissingProperty } from 'scenes/insights/utils/queryUtils'

import type { TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import type {
    ChartDisplayIcon,
    ChartDisplayOption,
} from 'products/product_analytics/frontend/insights/chartAlternatives/chartDisplayOptions'
import { getChartDisplayOptions } from 'products/product_analytics/frontend/insights/chartAlternatives/chartDisplayOptions'

function ChartFilterOptionLabel(props: { label: string; description?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{props.label}</span>
            <span className="text-xs text-tertiary font-normal">{props.description}</span>
        </div>
    )
}

function chartDisplayIcon(icon: ChartDisplayIcon): JSX.Element {
    switch (icon) {
        case 'area':
            return <IconAreaChart />
        case 'bar':
            return <IconGraph />
        case 'cumulative':
            return <IconCumulativeChart />
        case 'donut':
            return <IconDonutChart />
        case 'line':
            return <IconTrends />
        case 'metric':
            return <IconTrendingUp />
        case 'number':
            return <Icon123 />
        case 'pie':
            return <IconPieChart />
        case 'table':
            return <IconTableChart />
        case 'worldMap':
            return <IconGlobe />
    }
}

function chartDisplayOptionToSelectOption(option: ChartDisplayOption): LemonSelectOption<ChartDisplayType> {
    return {
        value: option.display,
        icon:
            option.display === ChartDisplayType.ActionsBarValue ? (
                <IconGraph className="rotate-90" />
            ) : option.display === ChartDisplayType.CalendarHeatmap ? (
                <IconRetentionHeatmap />
            ) : (
                chartDisplayIcon(option.icon)
            ),
        label: option.label,
        tooltip: option.tooltip,
        disabledReason: option.disabledReason,
        labelInMenu: <ChartFilterOptionLabel label={option.label} description={option.description} />,
    }
}

export function ChartFilter({
    fullWidth = false,
    disabledReason,
}: {
    fullWidth?: boolean
    disabledReason?: string
}): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const { isTrends, isSingleSeriesOutput, formula, formulaNodes, formulas, breakdownFilter, series } = useValues(
        insightVizDataLogic(insightProps)
    )
    const options: LemonSelectOptions<ChartDisplayType> = getChartDisplayOptions({
        isTrends,
        hasSingleSeriesOutput: isSingleSeriesOutput,
        hasTrendsFormula: !!formula || !!formulas?.length || !!formulaNodes?.length,
        breakdown: breakdownFilter?.breakdown,
        breakdowns: breakdownFilter?.breakdowns,
        boxPlotMissingProperty: isBoxPlotMissingProperty(series as TrendsQuery['series']),
        hasMetricInsight: !!featureFlags[FEATURE_FLAGS.METRIC_INSIGHT],
    }).map((group) => ({ title: group.title, options: group.options.map(chartDisplayOptionToSelectOption) }))

    return (
        <LemonSelect
            key="2"
            value={display || ChartDisplayType.ActionsLineGraph}
            onChange={(value) => {
                updateInsightFilter({ display: value })
            }}
            dropdownPlacement="bottom-end"
            optionTooltipPlacement="left"
            dropdownMatchSelectWidth={false}
            data-attr="chart-filter"
            options={options}
            size="small"
            fullWidth={fullWidth}
            disabledReason={editingDisabledReason ?? disabledReason}
        />
    )
}
