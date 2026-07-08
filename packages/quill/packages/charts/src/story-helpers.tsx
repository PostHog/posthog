import { fireEvent, waitFor } from '@testing-library/dom'

import { useChartTheme } from './core/theme'
import type { ChartTheme } from './core/types'

/**
 * Theme for stories, read from the quill data-viz CSS vars and kept in sync as
 * the active light/dark mode changes (the visual test runner flips the theme
 * for its second screenshot). Thin alias over the package's {@link useChartTheme}
 * so stories and product code resolve colors through the exact same reader.
 */
export function useReactiveTheme(): ChartTheme {
    return useChartTheme()
}

interface StageProps {
    children: React.ReactNode
    width?: number | string
    height?: number
}

/** Fixed-size chart container shared by stories so snapshots have stable geometry. */
export function Stage({ children, width = 480, height = 280 }: StageProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ width, height, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

/**
 * Dispatch a `mousemove` on the chart wrapper at a fraction of its width.
 * Used in `play` functions to make hover-driven overlays (tooltip, crosshair,
 * highlight ring) visible in screenshots.
 */
export async function playHoverAtFraction(
    canvasElement: HTMLElement,
    fraction: number,
    yFraction: number = 0.5
): Promise<void> {
    const wrapper = await waitFor(
        () => {
            const canvas = canvasElement.querySelector<HTMLCanvasElement>('canvas[role="img"]')
            const parent = canvas?.parentElement
            if (!parent) {
                throw new Error('chart wrapper not yet rendered')
            }
            const rect = parent.getBoundingClientRect()
            if (rect.width < 50 || rect.height < 50) {
                throw new Error('chart wrapper not yet sized')
            }
            return parent
        },
        { timeout: 3000 }
    )
    // Re-fire mousemove inside the waitFor: the chart's onMouseMove bails until
    // ResizeObserver has populated scales/dimensions, so a single dispatch races
    // the first measurement pass. Re-dispatching is cheap and idempotent.
    await waitFor(
        () => {
            const rect = wrapper.getBoundingClientRect()
            fireEvent.mouseMove(wrapper, {
                clientX: rect.left + rect.width * fraction,
                clientY: rect.top + rect.height * yFraction,
            })
            if (!document.querySelector('[data-hog-charts-tooltip]')) {
                throw new Error('tooltip not yet rendered')
            }
        },
        { timeout: 3000 }
    )
}
