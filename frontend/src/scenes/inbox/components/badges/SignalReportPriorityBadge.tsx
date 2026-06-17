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
}: {
    priority: SignalReportPriority | null | undefined
}): JSX.Element | null {
    if (priority == null) {
        return null
    }

    const color = PRIORITY_COLOR[priority]
    return (
        <span
            className="inline-flex size-6 items-center justify-center rounded-sm border text-[10px] font-semibold tabular-nums select-none"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                color,
                borderColor: `color-mix(in srgb, ${color} 40%, transparent)`,
                backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
            }}
        >
            {priority}
        </span>
    )
}
