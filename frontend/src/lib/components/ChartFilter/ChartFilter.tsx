import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isBoxPlotMissingProperty } from 'scenes/insights/utils/queryUtils'

import type { TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { ChartDisplayIcon } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartDisplayIcon'
import type { ChartDisplayOption } from 'products/product_analytics/frontend/insights/chartAlternatives/chartDisplayOptions'
import { getChartDisplayOptions } from 'products/product_analytics/frontend/insights/chartAlternatives/chartDisplayOptions'

import { QuillChartFilter } from './QuillChartFilter'

function ChartFilterOptionLabel(props: { label: string; description?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px]">
            <span>{props.label}</span>
            <span className="text-xs text-tertiary font-normal">{props.description}</span>
        </div>
    )
}

function chartDisplayOptionToSelectOption(option: ChartDisplayOption): LemonSelectOption<ChartDisplayType> {
    return {
        value: option.display,
        icon: <ChartDisplayIcon icon={option.icon} />,
        label: option.label,
        tooltip: option.tooltip,
        disabledReason: option.disabledReason,
        labelInMenu: <ChartFilterOptionLabel label={option.label} description={option.description} />,
    }
}

export function ChartFilter({
    fullWidth = false,
    disabledReason,
    onOpen,
}: {
    fullWidth?: boolean
    disabledReason?: string
    onOpen?: () => void
}): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { display, compareFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const { isTrends, isSingleSeriesOutput, formula, formulaNodes, formulas, breakdownFilter, series } = useValues(
        insightVizDataLogic(insightProps)
    )
    const groups = getChartDisplayOptions({
        isTrends,
        hasSingleSeriesOutput: isSingleSeriesOutput,
        hasTrendsFormula: !!formula || !!formulas?.length || !!formulaNodes?.length,
        breakdown: breakdownFilter?.breakdown,
        breakdowns: breakdownFilter?.breakdowns,
        boxPlotMissingProperty: isBoxPlotMissingProperty(series as TrendsQuery['series']),
        hasMetricInsight: !!featureFlags[FEATURE_FLAGS.METRIC_INSIGHT],
        isComparing: !!compareFilter?.compare,
    })

    if (todayRailNav) {
        return (
            <QuillChartFilter
                value={display || ChartDisplayType.ActionsLineGraph}
                groups={groups}
                onChange={(value) => updateInsightFilter({ display: value })}
                onOpen={onOpen}
                fullWidth={fullWidth}
                disabledReason={editingDisabledReason ?? disabledReason}
            />
        )
    }

    const options: LemonSelectOptions<ChartDisplayType> = groups.map((group) => ({
        title: group.title,
        options: group.options.map(chartDisplayOptionToSelectOption),
    }))

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
            menu={{ onVisibilityChange: (visible) => visible && onOpen?.() }}
            options={options}
            size="small"
            fullWidth={fullWidth}
            disabledReason={editingDisabledReason ?? disabledReason}
        />
    )
}
