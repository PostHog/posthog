import { cleanup, render, type RenderResult } from '@testing-library/react'
import React, { type ReactElement, type ReactNode } from 'react'

import { ChartLayoutContext, type ChartLayoutContextValue } from '../core/chart-context'
import type { ChartTheme, TooltipContext } from '../core/types'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { getHogChart, type HogChart } from './accessor'
import { ensureJsdom } from './jsdom'
import { HOG_CHARTS_TOOLTIP_SELECTOR } from './tooltip'

function buildDefaultLayoutContext(theme: ChartTheme): ChartLayoutContextValue {
    return {
        dimensions: { width: 0, height: 0, plotLeft: 0, plotTop: 0, plotWidth: 0, plotHeight: 0 },
        labels: [],
        series: [],
        scales: { x: () => 0, y: () => 0, yTicks: () => [] },
        theme,
        resolvePositionValue: (s, i) => s.data[i] ?? 0,
        canvasBounds: () => null,
        axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
    }
}

/** Render a hog-charts component and return Testing Library's `RenderResult` with a `chart`
 *  accessor attached. Throws if the rendered tree doesn't contain a hog-charts canvas.
 *
 *  Sets up the jsdom mocks + sync RAF on first call (idempotent), so tests don't need a
 *  beforeEach for those. Also calls `cleanup()` and removes any leftover tooltip portal
 *  before each render — RTL's auto-cleanup doesn't always reach `FloatingPortal` children. */
export function renderHogChart<Meta = unknown>(ui: ReactElement): RenderResult & { chart: HogChart<Meta> } {
    ensureJsdom()
    cleanup()
    document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR).forEach((el) => el.remove())

    // Intercept the (optional) `tooltip` render prop so `chart.waitForTooltip()` can return
    // the structured `TooltipContext` the chart computed. When the consumer passes a tooltip
    // we still call it for the rendered DOM; otherwise we fall through to DefaultTooltip,
    // matching the chart's natural default.
    let lastTooltipContext: TooltipContext<Meta> | null = null
    const props = ui.props as {
        tooltip?: (ctx: TooltipContext<Meta>) => ReactNode
        labels?: string[]
        theme: ChartTheme
    }
    const userTooltip = props.tooltip
    const captureTooltip = (ctx: TooltipContext<Meta>): ReactNode => {
        lastTooltipContext = ctx
        return userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx as TooltipContext)
    }
    const wrapped = (
        <ChartLayoutContext.Provider value={buildDefaultLayoutContext(props.theme)}>
            {React.cloneElement(ui, { tooltip: captureTooltip })}
        </ChartLayoutContext.Provider>
    )
    const result = render(wrapped)
    return {
        ...result,
        chart: getHogChart<Meta>(result.container, {
            getLastTooltipContext: () => lastTooltipContext,
            totalLabels: props.labels?.length,
        }),
    }
}
