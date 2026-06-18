import { IconQuestion } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { SignalReportPriority } from '../../types'

/**
 * Per-priority color, mirroring `PRIORITY_TAG_TYPE`'s LemonTag semantics but as raw CSS vars
 * so the badge can paint its own border + text. Theme-aware, so contrast holds in both modes.
 */
const PRIORITY_COLOR: Record<SignalReportPriority, string> = {
    P0: 'var(--danger)',
    P1: 'var(--warning)',
    P2: 'var(--danger-lighter)',
    P3: 'var(--color-accent)',
    P4: 'var(--color-text-secondary)',
}

/**
 * Sleek priority chip: a square box of accent text on a faint accent fill with a matching border
 * and a tight radius. Built bespoke since no LemonTag variant gives this filled-square look.
 * Shared verbatim between report cards and the detail header.
 */
export function SignalReportPriorityBadge({
    priority,
    explanation,
}: {
    priority: SignalReportPriority | null | undefined
    /**
     * When set, a circled help icon overlays the chip's top-right corner and the whole chip is
     * hoverable, surfacing this rationale. The icon is out of flow, so the chip stays a square.
     */
    explanation?: string | null
}): JSX.Element | null {
    if (priority == null) {
        return null
    }

    const color = PRIORITY_COLOR[priority]
    const borderColor = `color-mix(in srgb, ${color} 40%, transparent)`
    const chip = (
        <span
            className="inline-flex size-6 shrink-0 items-center justify-center rounded-sm border text-[10px] font-semibold tabular-nums select-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color,
                borderColor,
                backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
            }}
        >
            {priority}
        </span>
    )

    if (!explanation?.trim()) {
        return chip
    }
    // Icon center sits on the (rounded) top-right corner; matches the chip's text color, with its own bg to stay legible.
    return (
        <Tooltip title={explanation}>
            <span className="relative inline-flex cursor-help">
                {chip}
                <IconQuestion
                    className="absolute right-0 top-0 size-3 -translate-y-1/2 translate-x-1/2 rounded-full bg-surface-primary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color }}
                />
            </span>
        </Tooltip>
    )
}
