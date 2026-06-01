import { render, type RenderResult } from '@testing-library/react'
import type { ReactElement } from 'react'

import { getHogChart, type HogChart } from './accessor'

/** Render a hog-charts component and return Testing Library's `RenderResult`
 *  with a `chart` accessor attached. Throws if the rendered component doesn't
 *  emit a hog-charts canvas — use plain `render` for non-chart components. */
export function renderHogChart(ui: ReactElement): RenderResult & { chart: HogChart } {
    const result = render(ui)
    return { ...result, chart: getHogChart(result.container) }
}
