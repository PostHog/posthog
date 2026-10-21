import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import {
    AnomalyPointsLayer,
    LineChart,
    type LineChartConfig,
    type Series,
    type TooltipContext,
    TooltipSurface,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export type TodayTone = 'risk' | 'good' | 'neutral'

interface TodayTonePalette {
    risk: string
    good: string
    neutral: string
    line: string
}

const PALETTE: Record<'light' | 'dark', TodayTonePalette> = {
    light: { risk: '#d6453a', good: '#1f9d55', neutral: '#55554f', line: '#c4c4bc' },
    dark: { risk: '#ff7b6e', good: '#5fd38d', neutral: '#c9c9c2', line: '#55554f' },
}

export function useTodayTonePalette(): TodayTonePalette {
    const { isDarkModeOn } = useValues(themeLogic)
    return isDarkModeOn ? PALETTE.dark : PALETTE.light
}

export function TodaySparkline({
    values,
    labels,
    tone,
    emphasizeLast,
    formatValue,
}: {
    values: number[]
    labels: string[]
    tone: TodayTone
    emphasizeLast: number
    formatValue?: (value: number) => string
}): JSX.Element {
    const theme = useChartTheme()
    const palette = useTodayTonePalette()
    const last = values.length - 1
    const from = Math.max(0, values.length - 1 - emphasizeLast)
    const series = useMemo<Series[]>(
        () => [
            { key: 'trend', label: 'Value', data: values, color: palette.line },
            {
                key: 'recent',
                label: 'Recent',
                data: values.map((value, index) => (index >= from ? value : NaN)),
                color: palette[tone],
                visibility: { tooltip: false },
            },
        ],
        [values, from, palette, tone]
    )
    const config = useChartConfig<LineChartConfig>(
        () => ({
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: !!formatValue,
            curve: 'linear',
            floatBaseline: true,
            margins: { top: 4, right: 4, bottom: 4, left: 1 },
            tooltip: { enabled: !!formatValue, placement: 'follow-data' },
        }),
        [formatValue]
    )
    const tooltip = useCallback(
        (context: TooltipContext): JSX.Element | null => {
            const value = context.seriesData[0]?.value
            if (!formatValue || value === undefined || Number.isNaN(value)) {
                return null
            }
            return (
                <TooltipSurface>
                    <div className="opacity-70">{context.label}</div>
                    <div className="font-medium tabular-nums">{formatValue(value)}</div>
                </TooltipSurface>
            )
        },
        [formatValue]
    )

    return (
        <LineChart
            series={series}
            labels={labels}
            theme={theme}
            config={config}
            tooltip={tooltip}
            className="h-full w-full"
        >
            <AnomalyPointsLayer
                radius={2.5}
                markers={
                    last >= 0 ? [{ dataIndex: last, value: values[last], color: palette[tone], yAxisId: 'left' }] : []
                }
            />
        </LineChart>
    )
}
