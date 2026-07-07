import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonSegmentedButton } from '@posthog/lemon-ui'

import { useChartStyleRefreshEnabled } from 'lib/charts/hooks'
import { insightLogic } from 'scenes/insights/insightLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ChartStyle } from '~/queries/schema/schema-general'

function useChartStyle(): {
    chartStyle: ChartStyle
    updateChartStyle: (patch: Partial<ChartStyle>) => void
} {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { updateInsightFilter } = useActions(trendsDataLogic(insightProps))
    const chartStyle = trendsFilter?.chartStyle ?? {}
    return {
        chartStyle,
        updateChartStyle: (patch) => updateInsightFilter({ chartStyle: { ...chartStyle, ...patch } }),
    }
}

export function LineShapePicker(): JSX.Element {
    const { chartStyle, updateChartStyle } = useChartStyle()
    const styleRefreshEnabled = useChartStyleRefreshEnabled()
    // The app-level default curve depends on the chart style refresh rollout
    const effectiveCurve = chartStyle.curve ?? (styleRefreshEnabled ? 'smooth' : 'linear')

    return (
        <div className="flex items-center justify-between gap-2 px-2 pb-2 w-full">
            <span className="font-normal">Line shape</span>
            <LemonSegmentedButton
                size="small"
                value={effectiveCurve}
                onChange={(value) => updateChartStyle({ curve: value as ChartStyle['curve'] })}
                options={[
                    { value: 'linear', label: 'Straight' },
                    { value: 'smooth', label: 'Smooth' },
                ]}
            />
        </div>
    )
}

export function LineStylePicker(): JSX.Element {
    const { chartStyle, updateChartStyle } = useChartStyle()

    return (
        <div className="flex items-center justify-between gap-2 px-2 pb-2 w-full">
            <span className="font-normal">Line style</span>
            <LemonSegmentedButton
                size="small"
                value={chartStyle.lineStyle ?? 'solid'}
                onChange={(value) => updateChartStyle({ lineStyle: value as ChartStyle['lineStyle'] })}
                options={[
                    { value: 'solid', label: 'Solid' },
                    { value: 'dashed', label: 'Dashed' },
                    { value: 'dotted', label: 'Dotted' },
                ]}
            />
        </div>
    )
}

export function ShowPointsFilter(): JSX.Element {
    const { chartStyle, updateChartStyle } = useChartStyle()

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!chartStyle.showPoints}
            onChange={(checked) => updateChartStyle({ showPoints: checked })}
            label={<span className="font-normal">Show points</span>}
            size="small"
        />
    )
}

export function ShowGridLinesFilter(): JSX.Element {
    const { chartStyle, updateChartStyle } = useChartStyle()

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={chartStyle.showGrid !== false}
            onChange={(checked) => updateChartStyle({ showGrid: checked })}
            label={<span className="font-normal">Show gridlines</span>}
            size="small"
        />
    )
}
