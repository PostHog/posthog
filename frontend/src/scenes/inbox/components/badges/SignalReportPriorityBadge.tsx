import { Tooltip } from '@posthog/lemon-ui'

import { SignalReportPriority } from '../../types'
import { JudgmentWhyLabel } from './JudgmentWhyLabel'

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
    explanationDisplay = 'why-label',
}: {
    priority: SignalReportPriority | null | undefined
    /** When set, this report's priority rationale is surfaced via `explanationDisplay`. */
    explanation?: string | null
    /**
     * How to surface `explanation`: a "Why?" label beside the chip (default), or a tooltip on the
     * chip itself for compact contexts like list cards, where an affix would change the chip's width.
     */
    explanationDisplay?: 'why-label' | 'tooltip'
}): JSX.Element | null {
    if (priority == null) {
        return null
    }

    const color = PRIORITY_COLOR[priority]
    const hasExplanation = !!explanation?.trim()
    const asTooltip = hasExplanation && explanationDisplay === 'tooltip'
    const chip = (
        <span
            className={`inline-flex size-6 items-center justify-center rounded-sm border text-[10px] font-semibold tabular-nums select-none${
                asTooltip ? ' cursor-help' : ''
            }`}
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

    if (!hasExplanation) {
        return chip
    }
    if (explanationDisplay === 'tooltip') {
        return <Tooltip title={explanation}>{chip}</Tooltip>
    }
    return (
        <span className="inline-flex items-center gap-1">
            {chip}
            <JudgmentWhyLabel explanation={explanation} />
        </span>
    )
}
