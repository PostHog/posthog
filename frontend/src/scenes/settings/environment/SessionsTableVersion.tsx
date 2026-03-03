import { useActions } from 'kea'

import { LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

import { TeamSettingRadio } from '../components/TeamSettingRadio'

type SessionTableVersionType = NonNullable<HogQLQueryModifiers['sessionTableVersion']>

const sessionTableVersionOptions: LemonRadioOption<SessionTableVersionType>[] = [
    { value: 'auto', label: 'Auto' },
    { value: 'v1', label: 'Version 1' },
    { value: 'v2', label: 'Version 2' },
    { value: 'v3', label: 'Version 3' },
]

export function SessionsTableVersion(): JSX.Element {
    const { reportSessionTableVersionUpdated } = useActions(eventUsageLogic)

    return (
        <TeamSettingRadio
            field="modifiers.sessionTableVersion"
            options={sessionTableVersionOptions}
            defaultValue="auto"
            onSave={reportSessionTableVersionUpdated}
        />
    )
}
