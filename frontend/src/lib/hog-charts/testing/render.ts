import { cleanup, render, type RenderResult } from '@testing-library/react'
import React, { type ReactElement, type ReactNode } from 'react'

import type { TooltipContext } from '../core/types'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { getHogChart, type HogChart } from './accessor'
import { ensureJsdom } from './jsdom'
import { HOG_CHARTS_TOOLTIP_SELECTOR } from './tooltip'

export interface RenderHogChartOptions {
    /** Skip the tooltip-prop override so the chart renders its own tooltip. Context capture
     *  via `chart.waitForTooltip()` is unavailable in this mode. */
    nativeTooltip?: boolean
}

/** Render a hog-charts component and return Testing Library's `RenderResult` with a `chart`
 *  accessor attached. Throws if the rendered tree doesn't contain a hog-charts canvas.
 *
 *  Sets up the jsdom mocks + sync RAF on first call (idempotent), so tests don't need a
 *  beforeEach for those. Also calls `cleanup()` and removes any leftover tooltip portal
 *  before each render — RTL's auto-cleanup doesn't always reach `FloatingPortal` children. */
export function renderHogChart<Meta = unknown>(
    ui: ReactElement,
    options: RenderHogChartOptions = {}
): RenderResult & { chart: HogChart<Meta> } {
    ensureJsdom()
    cleanup()
    document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR).forEach((el) => el.remove())

    const props = ui.props as { tooltip?: (ctx: TooltipContext<Meta>) => ReactNode; labels?: string[] }

    // Intercept the `tooltip` render prop so `chart.waitForTooltip()` exposes the structured
    // `TooltipContext` the chart computed. Falls through to DefaultTooltip when no consumer
    // tooltip is supplied, matching the chart's natural default.
    let lastTooltipContext: TooltipContext<Meta> | null = null
    let toRender: ReactElement = ui
    if (!options.nativeTooltip) {
        const userTooltip = props.tooltip
        const captureTooltip = (ctx: TooltipContext<Meta>): ReactNode => {
            lastTooltipContext = ctx
            return userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx as TooltipContext)
        }
        toRender = React.cloneElement(ui, { tooltip: captureTooltip })
    }
    const result = render(toRender)
    return {
        ...result,
        chart: getHogChart<Meta>(result.container, {
            getLastTooltipContext: () => lastTooltipContext,
            totalLabels: props.labels?.length,
        }),
    }
}
