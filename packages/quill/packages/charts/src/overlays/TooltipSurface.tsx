import React from 'react'

import { useChartLayout } from '../core/chart-context'

/**
 * Fallback tooltip colors for hosts that don't supply them on `ChartTheme`.
 * An inverse panel (dark surface, light text), matching quill's tooltip — when
 * the quill theme reader is used these come from `--foreground` / `--background`.
 */
export const TOOLTIP_FALLBACK_BG = '#1d2330'
export const TOOLTIP_FALLBACK_COLOR = '#ffffff'

interface TooltipSurfaceProps {
    children: React.ReactNode
    className?: string
    /** Forwarded onto the panel — used for test/automation selectors. */
    'data-attr'?: string
}

/**
 * Shared surface for the built-in chart tooltips. Geometry mirrors quill's
 * tooltip (`.quill-tooltip__content`: inverse panel, `radius-sm`, compact
 * padding, `text-xs`) but is applied inline — no shipped stylesheet, no Tailwind
 * scan needed, so the floating panel renders correctly regardless of the
 * consumer's setup. Dimensions reference quill token vars with literal
 * fallbacks; colors stay theme-driven so non-quill hosts can restyle.
 */
export function TooltipSurface({
    children,
    className,
    'data-attr': dataAttr,
}: TooltipSurfaceProps): React.ReactElement {
    const { theme } = useChartLayout()
    return (
        <div
            className={className}
            data-attr={dataAttr}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: 'fit-content',
                maxWidth: '20rem',
                paddingBlock: '0.375rem',
                paddingInline: '0.75rem',
                fontSize: 'var(--text-xs, 0.75rem)',
                lineHeight: 1.4,
                borderRadius: 'var(--radius-sm, 0.375rem)',
                // Soft float shadow for separation over dense chart data — the
                // one intentional addition over quill's flat in-page tooltip.
                boxShadow: '0 2px 8px rgb(0 0 0 / 18%)',
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
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                display: 'inline-block',
                flex: 'none',
                width: '0.5rem',
                height: '0.5rem',
                borderRadius: '9999px',
                backgroundColor: color,
            }}
        />
    )
}
