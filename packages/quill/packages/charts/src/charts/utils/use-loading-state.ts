import { useMemo } from 'react'

import type { ChartTheme, Series, ValueDomain } from '../../core/types'

const SKELETON_FALLBACK = 'rgba(140, 140, 150, 0.35)'

/** Pinned y-domain for the animated line skeleton — the drifting wave's extent varies with
 *  phase, so a data-derived domain would rescale (and visibly pump) the axis every frame. */
export const SKELETON_VALUE_DOMAIN: ValueDomain = [0, 100]


/** Fixed y-gutter while loading — y tick labels are hidden (their values would be fake),
 *  so reserve a width close to a typical numeric gutter to minimize shift when data lands. */
export const SKELETON_MARGINS = { left: 36 }

/** Hides y tick labels while keeping the tick positions (gridlines) intact. */
export const HIDDEN_TICK_FORMATTER = (): string => ''

/** Labels used when a loading chart has no known x-domain; x labels are hidden alongside. */
export const FALLBACK_SKELETON_LABELS: string[] = Array.from({ length: 12 }, (_, i) => String(i))

export interface ChartLoadingProps {
    /** Render a skeleton preview instead of data: real x-axis from `labels`, placeholder
     *  marks, interactions off. Pass the known labels (date range × interval) so the
     *  x-axis matches what the loaded chart will show. */
    loading?: boolean
    /** Keep rendering the current data, dimmed, while a refetch is in flight —
     *  interactions off. Ignored while `loading`. */
    refreshing?: boolean
    /** Centered over the plot while `loading` or `refreshing` — host progress UI. */
    loadingOverlay?: React.ReactNode
}

export function skeletonColorFor(theme: ChartTheme): string {
    return theme.skeletonColor ?? theme.gridColor ?? SKELETON_FALLBACK
}

/** Curvy line trending upward, from ~20% of the plot to ~90% — reads as "a trend line goes
 *  here". Static; the loading shimmer overlay provides the movement. */
export function placeholderWave(count: number): number[] {
    if (count <= 1) {
        return count === 1 ? [20] : []
    }
    return Array.from({ length: count }, (_, i) => {
        const t = i / (count - 1)
        return 20 + t * 62 + 9 * Math.sin(i / 1.9) + 4 * Math.sin(i * 0.8)
    })
}


/** Deterministic staggered columns for bar skeletons. */
export function placeholderColumns(count: number): number[] {
    return Array.from({ length: count }, (_, i) => 30 + ((i * 37) % 47) + Math.round(14 * Math.sin(i / 1.9)))
}

/** The skeleton series drawn while `loading`; `null` otherwise. */
export function useLoadingSeries<Meta = unknown>(
    kind: 'line' | 'bar',
    labels: string[],
    theme: ChartTheme,
    loading: boolean
): Series<Meta>[] | null {
    return useMemo(() => {
        if (!loading) {
            return null
        }
        const color = skeletonColorFor(theme)
        if (kind === 'line') {
            return [
                {
                    key: '__skeleton__',
                    label: 'Loading',
                    data: placeholderWave(labels.length),
                    color,
                    fill: { opacity: 0.35 },
                    points: { radius: 0 },
                },
            ]
        }
        return [{ key: '__skeleton__', label: 'Loading', data: placeholderColumns(labels.length), color }]
    }, [kind, labels, theme, loading])
}
