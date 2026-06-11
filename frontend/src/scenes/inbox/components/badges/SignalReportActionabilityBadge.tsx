import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { SignalReportActionability } from '../../types'

const ACTIONABILITY_STYLE: Record<SignalReportActionability, { type: LemonTagType; label: string }> = {
    immediately_actionable: { type: 'success', label: 'Actionable' },
    requires_human_input: { type: 'caution', label: 'Needs input' },
    not_actionable: { type: 'muted', label: 'Not actionable' },
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
        <LemonTag size="small" type={style.type} className="select-none">
            {style.label}
        </LemonTag>
    )
}
