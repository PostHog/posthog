import { getColorVar, getGraphColors, getSeriesColorPalette } from 'lib/colors'

import type { ChartTheme } from '../types'

export function buildTheme(overrides?: Partial<ChartTheme>): ChartTheme {
    const graphColors = getGraphColors()

    const base: ChartTheme = {
        colors: getSeriesColorPalette(),
        backgroundColor:
            getComputedStyle(document.body).getPropertyValue('--color-bg-surface-primary').trim() || '#ffffff',
        axisColor: graphColors.axisLabel ?? undefined,
        gridColor: graphColors.axisLine ?? undefined,
        crosshairColor: graphColors.crosshair ?? undefined,
        // Surface-following popover, not the inverse --color-bg-surface-tooltip — stays dark in dark mode.
        tooltipBackground: getColorVar('color-bg-surface-popover'),
        tooltipColor: getColorVar('color-text-primary'),
        tooltipZIndex: 'var(--z-chart-tooltip)',
    }

    if (!overrides) {
        return base
    }
    return { ...base, ...overrides }
}

export function seriesColor(theme: ChartTheme, index: number): string {
    return theme.colors[index % theme.colors.length]
}
