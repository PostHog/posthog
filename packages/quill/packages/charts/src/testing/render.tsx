import { cleanup, render, type RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'

import type { TooltipContext } from '../core/types'
import { TooltipCaptureProvider } from '../overlays/Tooltip'
import { type ChartAccessor, getChart } from './accessor'
import { ensureJsdom } from './jsdom'
import { TOOLTIP_SELECTOR } from './tooltip'

/** Render a quill-charts component and return Testing Library's `RenderResult` with a `chart`
 *  accessor attached. Throws if the rendered tree doesn't contain a quill-charts canvas.
 *
 *  Sets up the jsdom mocks + sync RAF on first call (idempotent), so tests don't need a
 *  beforeEach for those. Also calls `cleanup()` and removes any leftover tooltip portal
 *  before each render — RTL's auto-cleanup doesn't always reach `FloatingPortal` children. */
export function renderChart<Meta = unknown>(ui: ReactElement): RenderResult & { chart: ChartAccessor<Meta> } {
    ensureJsdom()
    cleanup()
    document.querySelectorAll(TOOLTIP_SELECTOR).forEach((el) => el.remove())

    let lastTooltipContext: TooltipContext<Meta> | null = null
    const capture = (ctx: TooltipContext): void => {
        lastTooltipContext = ctx as TooltipContext<Meta>
    }
    // A `wrapper` survives `rerender`, which would drop a provider written around `ui`.
    const result = render(ui, {
        wrapper: ({ children }) => <TooltipCaptureProvider value={capture}>{children}</TooltipCaptureProvider>,
    })
    return {
        ...result,
        chart: getChart<Meta>(result.container, { getLastTooltipContext: () => lastTooltipContext }),
    }
}
