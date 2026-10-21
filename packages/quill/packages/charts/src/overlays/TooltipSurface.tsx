import React, { useContext } from 'react'

import { ChartLayoutContext } from '../core/chart-context'

// Fallback colors for non-quill hosts; quill hosts get --card / --foreground from the theme reader.
export const TOOLTIP_FALLBACK_BG = '#1d2330'
export const TOOLTIP_FALLBACK_COLOR = '#ffffff'

// Outside a chart there is no theme, so read the same tokens the theme reader does.
const STANDALONE_BG = `var(--card, var(--color-bg-surface-popover, ${TOOLTIP_FALLBACK_BG}))`
const STANDALONE_COLOR = `var(--foreground, var(--color-text-primary, ${TOOLTIP_FALLBACK_COLOR}))`

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
    const theme = useContext(ChartLayoutContext)?.theme
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
                backgroundColor: theme ? (theme.tooltipBackground ?? TOOLTIP_FALLBACK_BG) : STANDALONE_BG,
                color: theme ? (theme.tooltipColor ?? TOOLTIP_FALLBACK_COLOR) : STANDALONE_COLOR,
            }}
        >
            {children}
        </div>
    )
}

/** Divider plus muted row below a tooltip's content — e.g. a "click to inspect" hint. */
export function TooltipFooter({ children }: { children: React.ReactNode }): React.ReactElement {
    return <div className="mt-1 pt-1 border-t border-current/25 text-xs opacity-60 text-center">{children}</div>
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
