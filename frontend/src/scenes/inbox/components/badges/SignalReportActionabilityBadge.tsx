import { IconQuestion } from '@posthog/icons'
import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { SignalReportActionability } from '../../types'

// `textColor` mirrors the LemonTag text color for each `type` (see LemonTag.scss; for these outlined
// types the text and border share the same var), so the overlaid help icon matches the tag's text.
const ACTIONABILITY_STYLE: Record<
    SignalReportActionability,
    { type: LemonTagType; label: string; tooltip: string; textColor: string }
> = {
    immediately_actionable: {
        type: 'success',
        label: 'Actionable',
        tooltip:
            "The issue can be solved with code. If there isn't a pull request yet, it fell below your auto-PR priority threshold – you can still start one from this report.",
        textColor: 'var(--success)',
    },
    requires_human_input: {
        type: 'caution',
        label: 'Needs input',
        tooltip:
            'Actionable, but it needs your input first to decide how to resolve it: business context, trade-offs, or a choice between several valid approaches.',
        textColor: 'var(--danger-lighter)',
    },
    not_actionable: {
        type: 'muted',
        label: 'Not actionable',
        tooltip:
            'No useful code change can be derived – the report is too vague, lacks supporting evidence, or describes expected behavior.',
        textColor: 'var(--color-text-secondary)',
    },
}

export function SignalReportActionabilityBadge({
    actionability,
    explanation,
}: {
    actionability: SignalReportActionability | null | undefined
    /**
     * When set, a circled help icon overlays the tag's top-right corner and the rationale becomes the
     * tag's tooltip (replacing the generic category blurb). Absent, the tag shows the generic meaning.
     */
    explanation?: string | null
}): JSX.Element | null {
    if (actionability == null) {
        return null
    }

    const style = ACTIONABILITY_STYLE[actionability]
    if (!style) {
        return null
    }

    const tag = (
        <LemonTag size="small" type={style.type} className="cursor-help select-none">
            {style.label}
        </LemonTag>
    )

    if (!explanation?.trim()) {
        return <Tooltip title={style.tooltip}>{tag}</Tooltip>
    }
    // Icon center sits on the (rounded) top-right corner; its own bg keeps it legible over the tag edge.
    return (
        <Tooltip title={explanation}>
            <span className="relative inline-flex cursor-help">
                {tag}
                <IconQuestion
                    className="absolute right-0 top-0 size-3 -translate-y-1/2 translate-x-1/2 rounded-full bg-surface-primary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color: style.textColor }}
                />
            </span>
        </Tooltip>
    )
}
