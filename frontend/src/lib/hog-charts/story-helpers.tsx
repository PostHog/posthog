import { fireEvent, waitFor } from '@testing-library/dom'
import { useEffect, useState } from 'react'

import type { ChartTheme } from './core/types'

const DATA_COLOR_VARS = [
    'data-color-1',
    'data-color-2',
    'data-color-3',
    'data-color-4',
    'data-color-5',
    'data-color-6',
    'data-color-7',
    'data-color-8',
    'data-color-9',
    'data-color-10',
    'data-color-11',
    'data-color-12',
    'data-color-13',
    'data-color-14',
    'data-color-15',
]

function readCssVar(name: string): string | undefined {
    const value = getComputedStyle(document.body)
        .getPropertyValue('--' + name)
        .trim()
    return value || undefined
}

function buildTheme(): ChartTheme {
    return {
        colors: DATA_COLOR_VARS.map((v) => readCssVar(v) ?? '#000'),
        backgroundColor: readCssVar('color-bg-surface-primary') ?? '#ffffff',
        axisColor: readCssVar('color-graph-axis-label'),
        gridColor: readCssVar('color-graph-axis-line'),
        crosshairColor: readCssVar('color-graph-crosshair'),
        tooltipBackground: readCssVar('color-bg-surface-tooltip'),
        tooltipColor: readCssVar('color-text-primary-inverse'),
    }
}

/**
 * `buildTheme()` reads CSS variables from `document.body` once. The Storybook
 * test runner takes a second screenshot after flipping `body[theme="dark"]`,
 * but stories that captured the theme at first render keep light-mode colors
 * in the dark snapshot. This hook re-evaluates `buildTheme()` whenever the
 * theme attribute changes so the chart's own colors actually update.
 */
export function useReactiveTheme(): ChartTheme {
    const [theme, setTheme] = useState<ChartTheme>(() => buildTheme())
    useEffect(() => {
        const observer = new MutationObserver(() => setTheme(buildTheme()))
        observer.observe(document.body, { attributes: true, attributeFilter: ['theme', 'class'] })
        return () => observer.disconnect()
    }, [])
    return theme
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
