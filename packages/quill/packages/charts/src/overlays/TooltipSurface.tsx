import React from 'react'

import { useChartLayout } from '../core/chart-context'

// Fallback colors for non-quill hosts; quill hosts get --card / --foreground from the theme reader.
export const TOOLTIP_FALLBACK_BG = '#1d2330'
export const TOOLTIP_FALLBACK_COLOR = '#ffffff'

interface TooltipSurfaceProps {
    children: React.ReactNode
    className?: string
    /** Forwarded onto the panel — used for test/automation selectors. */
    'data-attr'?: string
}

// Styled inline (no shipped stylesheet) so the floating panel renders regardless of host setup.
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
                paddingInline: '0.5rem',
                fontSize: 'var(--text-xs, 0.75rem)',
                lineHeight: 1.4,
                borderRadius: 'var(--radius-sm, 0.375rem)',
                // Soft float shadow for separation over dense chart data — the
                // one intentional addition over quill's flat in-page tooltip.
                border: '1px solid rgba(255, 255, 255, 0.1)',
                boxShadow: '0 4px 16px rgb(0 0 0 / 40%)',
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
            data-attr="hog-chart-tooltip-swatch"
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
