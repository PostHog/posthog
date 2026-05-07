import { render, type RenderResult } from '@testing-library/react'
import React, { type ReactElement, type ReactNode } from 'react'

import type { TooltipContext } from '../core/types'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { getHogChart, type HogChart } from './accessor'

/** Render a hog-charts component and return Testing Library's `RenderResult`
 *  with a `chart` accessor attached. Throws if the rendered component doesn't
 *  emit a hog-charts canvas — use plain `render` for non-chart components.
 *
 *  The `tooltip` render prop is intercepted so `chart.waitForTooltip()` can
 *  return the structured `TooltipContext` the chart computed; any user-supplied
 *  tooltip prop is still invoked for its rendered DOM. */
export function renderHogChart<Meta = unknown>(ui: ReactElement): RenderResult & { chart: HogChart<Meta> } {
    let lastTooltipContext: TooltipContext<Meta> | null = null
    const userTooltip = (ui.props as { tooltip?: (ctx: TooltipContext<Meta>) => ReactNode }).tooltip
    const captureTooltip = (ctx: TooltipContext<Meta>): ReactNode => {
        lastTooltipContext = ctx
        return userTooltip ? userTooltip(ctx) : DefaultTooltip(ctx as TooltipContext)
    }
    const wrapped = React.cloneElement(ui, { tooltip: captureTooltip })
    const result = render(wrapped)
    return {
        ...result,
        chart: getHogChart<Meta>(result.container, () => lastTooltipContext),
    }
}
