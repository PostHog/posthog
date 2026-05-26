import { cleanup, render, type RenderResult } from '@testing-library/react'
import React, { type ReactElement, type ReactNode } from 'react'

import type { TooltipContext } from '../core/types'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { getHogChart, type HogChart } from './accessor'
import { ensureJsdom } from './jsdom'
import { HOG_CHARTS_TOOLTIP_SELECTOR } from './tooltip'

export interface RenderHogChartOptions {
    /** When true, do not intercept the chart's `tooltip` prop. The chart renders its own
     *  internal tooltip component (e.g. BoxPlotTooltip), letting tests assert on real DOM
     *  output. In this mode `chart.waitForTooltip()` still returns the portal element and
     *  `isPinned`, but the structured `TooltipContext` fields throw on access — use the
     *  default mode when you need context capture. */
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

    // Default: intercept the (optional) `tooltip` render prop so `chart.waitForTooltip()` can
    // return the structured `TooltipContext` the chart computed. When the consumer passes a
    // tooltip we still call it for the rendered DOM; otherwise we fall through to
    // DefaultTooltip, matching the chart's natural default.
    // `nativeTooltip`: skip the override so the chart renders its own internal tooltip.
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
