import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { SignalReportPriority } from '../../types'

const PRIORITY_TYPE: Record<SignalReportPriority, LemonTagType> = {
    P0: 'danger',
    P1: 'warning',
    P2: 'warning',
    P3: 'default',
    P4: 'default',
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
