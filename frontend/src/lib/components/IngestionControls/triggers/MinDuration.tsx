import { LemonSelect } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS, TeamMembershipLevel } from 'lib/constants'

export function MinDurationTrigger({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (value: number | null | undefined) => void
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonSelect
            dropdownMatchSelectWidth={false}
            onChange={onChange}
            options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS}
            value={value}
            disabledReason={restrictedReason}
        />
    )
}
