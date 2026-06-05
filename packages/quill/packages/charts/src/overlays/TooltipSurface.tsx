import React from 'react'

import { useChartLayout } from '../core/chart-context'

/**
 * Fallback tooltip colors for hosts that don't supply them on `ChartTheme`.
 * An inverse panel (dark surface, light text), matching quill's tooltip — when
 * the quill theme reader is used these come from `--foreground` / `--background`.
 */
export const TOOLTIP_FALLBACK_BG = '#1d2330'
export const TOOLTIP_FALLBACK_COLOR = '#ffffff'

function joinClasses(...parts: Array<string | undefined>): string {
    return parts.filter(Boolean).join(' ')
}

interface TooltipSurfaceProps {
    children: React.ReactNode
    className?: string
    /** Forwarded onto the panel — used for test/automation selectors. */
    'data-attr'?: string
}

/**
 * Shared surface for the built-in chart tooltips. Mirrors quill's tooltip
 * (`.quill-tooltip__content`): an inverse panel at `radius-sm`, compact padding,
 * `text-xs`. Colors stay theme-driven so non-quill hosts can still restyle it.
 * The shadow is the one intentional deviation from the primitive — chart
 * tooltips float over dense data and need the extra separation.
 */
export function TooltipSurface({
    children,
    className,
    'data-attr': dataAttr,
}: TooltipSurfaceProps): React.ReactElement {
    const { theme } = useChartLayout()
    return (
        <div
            className={joinClasses('rounded-sm px-3 py-1.5 text-xs shadow-md', className)}
            data-attr={dataAttr}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                backgroundColor: theme.tooltipBackground ?? TOOLTIP_FALLBACK_BG,
                color: theme.tooltipColor ?? TOOLTIP_FALLBACK_COLOR,
            }}
        >
            {children}
        </div>
    )
}

/** Round series-color swatch used in tooltip rows. */
export function TooltipSwatch({ color }: { color: string }): React.ReactElement {
    return (
        <span
            className="inline-block size-2 rounded-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: color }}
        />
    )
}
