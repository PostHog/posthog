import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { SignalReportActionability } from '../../types'

const ACTIONABILITY_STYLE: Record<SignalReportActionability, { type: LemonTagType; label: string; tooltip: string }> = {
    immediately_actionable: {
        type: 'success',
        label: 'Actionable',
        tooltip:
            "The issue can be solved with code. If there isn't a pull request yet, it fell below your auto-PR priority threshold – you can still start one from this report.",
    },
    requires_human_input: {
        type: 'caution',
        label: 'Needs input',
        tooltip:
            'Actionable, but it needs your input first to decide how to resolve it: business context, trade-offs, or a choice between several valid approaches.',
    },
    not_actionable: {
        type: 'muted',
        label: 'Not actionable',
        tooltip:
            'No useful code change can be derived – the report is too vague, lacks supporting evidence, or describes expected behavior.',
    },
}

export function SignalReportActionabilityBadge({
    actionability,
}: {
    actionability: SignalReportActionability | null | undefined
}): JSX.Element | null {
    if (actionability == null) {
        return null
    }

    const style = ACTIONABILITY_STYLE[actionability]
    if (!style) {
        return null
    }

    return (
        <Tooltip title={style.tooltip}>
            <LemonTag size="small" type={style.type} className="cursor-help select-none">
                {style.label}
            </LemonTag>
        </Tooltip>
    )
}
