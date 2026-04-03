import { useActions } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { TeamSettingRadio } from '../components/TeamSettingRadio'

type SessionTableVersionType = NonNullable<HogQLQueryModifiers['sessionTableVersion']>

const SESSION_TABLE_VERSION_OPTIONS: LemonRadioOption<SessionTableVersionType>[] = [
    { value: 'auto', label: 'Auto' },
    { value: 'v1', label: 'Version 1' },
    { value: 'v2', label: 'Version 2' },
    { value: 'v3', label: 'Version 3' },
]

export function SessionsTableVersion(): JSX.Element {
    const { reportSessionTableVersionUpdated } = useActions(eventUsageLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const sessionTableVersionOptions = SESSION_TABLE_VERSION_OPTIONS.map((o) => ({
        ...o,
        disabledReason: restrictedReason ?? undefined,
    }))

    return (
        <TeamSettingRadio
            field="modifiers.sessionTableVersion"
            options={sessionTableVersionOptions}
            defaultValue="auto"
            onSave={reportSessionTableVersionUpdated}
            disabledReason={restrictedReason}
        />
    )
}
