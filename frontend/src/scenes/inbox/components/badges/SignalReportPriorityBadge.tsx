import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { SignalReportPriority } from '../../types'

// Descending visual weight: P0 reads as an alarm, P4 fades into muted.
const PRIORITY_TYPE: Record<SignalReportPriority, LemonTagType> = {
    P0: 'danger',
    P1: 'warning',
    P2: 'caution',
    P3: 'default',
    P4: 'muted',
}

export function SignalReportPriorityBadge({
    priority,
}: {
    priority: SignalReportPriority | null | undefined
}): JSX.Element | null {
    if (priority == null) {
        return null
    }

    return (
        <LemonTag size="small" type={PRIORITY_TYPE[priority]} className="select-none">
            {priority}
        </LemonTag>
    )
}
