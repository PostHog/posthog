import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { TeamSettingRadio } from '../components/TeamSettingRadio'

type SessionsV2JoinModeType = NonNullable<HogQLQueryModifiers['sessionsV2JoinMode']>

const SESSIONS_V2_JOIN_MODE_OPTIONS: LemonRadioOption<SessionsV2JoinModeType>[] = [
    { value: 'string', label: 'String' },
    { value: 'uuid', label: 'UUID' },
]

export function SessionsV2JoinModeSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const sessionsV2JoinModeOptions = SESSIONS_V2_JOIN_MODE_OPTIONS.map((o) => ({
        ...o,
        disabledReason: restrictedReason ?? undefined,
    }))

    return (
        <TeamSettingRadio
            field="modifiers.sessionsV2JoinMode"
            options={sessionsV2JoinModeOptions}
            defaultValue="string"
            disabledReason={restrictedReason}
        />
    )
}
