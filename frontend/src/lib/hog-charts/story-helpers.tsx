import { fireEvent, waitFor } from '@testing-library/react'
import { useEffect, useState } from 'react'

import { buildTheme } from 'lib/charts/utils/theme'

import type { ChartTheme } from './core/types'

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
    const rect = wrapper.getBoundingClientRect()
    fireEvent.mouseMove(wrapper, {
        clientX: rect.left + rect.width * fraction,
        clientY: rect.top + rect.height * yFraction,
    })
    await waitFor(
        () => {
            if (!document.querySelector('[data-hog-charts-tooltip]')) {
                throw new Error('tooltip not yet rendered')
            }
        },
        { timeout: 1000 }
    )
}
