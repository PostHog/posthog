import { getGraphColors, getSeriesColorPalette } from 'lib/colors'

import type { ChartTheme } from '../types'

export function buildTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const graphColors = getGraphColors()

    const base: ChartTheme = {
        colors: getSeriesColorPalette(),
        axisColor: graphColors.axisLabel ?? undefined,
        gridColor: graphColors.axisLine ?? undefined,
        crosshairColor: graphColors.crosshair ?? undefined,
        tooltipBackground: graphColors.tooltipBackground ?? undefined,
        tooltipColor: graphColors.tooltipTitle ?? undefined,
    }

    if (!overrides) {
        return base
    }
    return { ...base, ...overrides }
}

export function seriesColor(theme: ChartTheme, index: number): string {
    return theme.colors[index % theme.colors.length]
}
