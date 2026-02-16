import { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { TeamSettingRadio } from '../components/TeamSettingRadio'

type SessionsV2JoinModeType = NonNullable<HogQLQueryModifiers['sessionsV2JoinMode']>

const sessionsV2JoinModeOptions: LemonRadioOption<SessionsV2JoinModeType>[] = [
    { value: 'string', label: 'String' },
    { value: 'uuid', label: 'UUID' },
]

export function SessionsV2JoinModeSettings(): JSX.Element {
    return (
        <TeamSettingRadio
            field="modifiers.sessionsV2JoinMode"
            options={sessionsV2JoinModeOptions}
            defaultValue="string"
        />
    )
}
