import {
    arrow,
    autoUpdate,
    flip,
    FloatingArrow,
    FloatingPortal,
    offset,
    shift,
    useFloating,
    useHover,
    useInteractions,
    useRole,
} from '@floating-ui/react'
import React, { useRef, useState } from 'react'

import { TOOLTIP_FALLBACK_BG, TOOLTIP_FALLBACK_COLOR } from '../../overlays/TooltipSurface'
import { percentage } from '../../utils/format'

export interface ChangeColor {
    background: string
    foreground: string
}

export const DEFAULT_POSITIVE_COLOR: ChangeColor = { background: 'rgb(56 134 0 / 10%)', foreground: '#388600' }
export const DEFAULT_NEGATIVE_COLOR: ChangeColor = { background: 'rgb(219 55 7 / 10%)', foreground: '#db3707' }

export const DEFAULT_FORMAT_VALUE = (v: number): string => v.toLocaleString()
export const DEFAULT_FORMAT_CHANGE = (p: number): string => {
    const formatted = percentage(p / 100, 1, true)
    return p > 0 ? `+${formatted}` : formatted
}

// Percent change from the point before `index` to the point at `index`. Returns null when there is
// no usable previous point (first index, missing/non-finite values, or a zero baseline).
export function changeFromPreviousPoint(data: number[], index: number): number | null {
    const prev = data[index - 1]
    const curr = data[index]
    if (index < 1 || prev === 0 || !Number.isFinite(prev) || !Number.isFinite(curr)) {
        return null
    }
    return ((curr - prev) / Math.abs(prev)) * 100
}

// The hover-driven change percent: the hovered point vs the previous point when
// `hoverChangeFromPreviousPoint` is active, otherwise the live value vs the series baseline.
export function computeFallbackChangePercent(
    sparklineData: number[] | null,
    usePrevPointHover: boolean,
    intentIndex: number,
    liveValue: number,
    baselineValue: number | undefined
): number | null {
    if (sparklineData == null) {
        return null
    }
    if (usePrevPointHover) {
        return changeFromPreviousPoint(sparklineData, intentIndex)
    }
    if (baselineValue == null) {
        return null
    }
    return ((liveValue - baselineValue) / Math.abs(baselineValue)) * 100
}

export interface ChangePillProps {
    positive: boolean
    label: React.ReactNode
    colors: ChangeColor
    size?: 'sm' | 'md'
    tooltip?: string
}

export function ChangePill({ positive, label, colors, size = 'sm', tooltip }: ChangePillProps): React.ReactElement {
    const sizeClasses = size === 'md' ? 'gap-1.5 px-2.5 py-1 text-sm' : 'gap-1 px-2 py-0.5 text-xs'
    const pill = (
        <div
            className={`inline-flex items-center rounded-full font-medium transition-colors ${sizeClasses}`}
            style={{ background: colors.background, color: colors.foreground }}
            data-attr="metric-card-change-pill"
        >
            <Chevron up={positive} size={size === 'md' ? 12 : 10} />
            <span className="tabular-nums">{label}</span>
        </div>
    )
    if (!tooltip) {
        return pill
    }
    return <ChangePillTooltip content={tooltip}>{pill}</ChangePillTooltip>
}

// A hover tooltip for the change pill. Built on floating-ui directly so the charts package stays
// dependency-light (no app Tooltip import), but styled with the app's tooltip surface tokens so it
// reads as a normal PostHog tooltip and stays legible over the tile's own --card background. Falls
// back to the chart tooltip constants in non-app hosts that don't define those vars.
const TOOLTIP_BG = `var(--color-bg-surface-tooltip, ${TOOLTIP_FALLBACK_BG})`
const TOOLTIP_COLOR = `var(--color-text-primary-inverse, ${TOOLTIP_FALLBACK_COLOR})`

function ChangePillTooltip({
    content,
    children,
}: {
    content: React.ReactNode
    children: React.ReactNode
}): React.ReactElement {
    const [open, setOpen] = useState(false)
    const arrowRef = useRef<SVGSVGElement>(null)
    const { refs, floatingStyles, context } = useFloating({
        open,
        onOpenChange: setOpen,
        placement: 'top',
        strategy: 'fixed',
        whileElementsMounted: autoUpdate,
        middleware: [offset(8), flip(), shift({ padding: 8 }), arrow({ element: arrowRef })],
    })
    const hover = useHover(context, { move: false })
    const role = useRole(context, { role: 'tooltip' })
    const { getReferenceProps, getFloatingProps } = useInteractions([hover, role])

    return (
        <>
            <span ref={refs.setReference} {...getReferenceProps()} className="inline-flex">
                {children}
            </span>
            {open && (
                <FloatingPortal>
                    <div
                        ref={refs.setFloating}
                        {...getFloatingProps()}
                        className="pointer-events-none max-w-80 rounded-md px-3 py-1.5 text-xs font-normal leading-snug"
                        // Dynamic only: floating-ui position + app tooltip tokens. Static styling stays in Tailwind.
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            ...floatingStyles,
                            zIndex: 'var(--z-tooltip, 9999)',
                            background: TOOLTIP_BG,
                            color: TOOLTIP_COLOR,
                            boxShadow: 'var(--modal-shadow-elevation, 0 2px 8px rgb(0 0 0 / 18%))',
                        }}
                    >
                        {content}
                        {/* `currentColor` + the bg-colored `color` paints the arrow the same surface color
                            (a CSS var can't go in the SVG `fill` attribute directly). */}
                        <FloatingArrow
                            ref={arrowRef}
                            context={context}
                            fill="currentColor"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ color: TOOLTIP_BG }}
                        />
                    </div>
                </FloatingPortal>
            )}
        </>
    )
}

function Chevron({ up, size = 10 }: { up: boolean; size?: number }): React.ReactElement {
    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 10 10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={up ? '' : 'rotate-180'}
        >
            <path d="M2 6.5 L5 3.5 L8 6.5" />
        </svg>
    )
}
