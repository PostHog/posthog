import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

type PersonsJoinMode = NonNullable<HogQLQueryModifiers['personsJoinMode']>

const personsJoinOptions: LemonRadioOption<PersonsJoinMode>[] = [
    {
        value: 'inner',
        label: (
            <>
                <div>Does an inner join</div>
                <div className="text-secondary">
                    This is the default. You want this one unless you know what you are doing.
                </div>
            </>
        ),
    },
    {
        value: 'left',
        label: (
            <>
                <div>Does a left join.</div>
                <div className="text-secondary">Experimental mode for personless events </div>
            </>
        ),
    },
]

export function PersonsJoinMode(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportPersonsJoinModeUpdated } = useActions(eventUsageLogic)

    const savedPersonsJoinMode =
        currentTeam?.modifiers?.personsJoinMode ?? currentTeam?.default_modifiers?.personsJoinMode ?? 'inner'
    const [personsJoinMode, setPersonsJoinMode] = useState<PersonsJoinMode>(savedPersonsJoinMode)

    const handleChange = (mode: PersonsJoinMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, personsJoinMode: mode } })
        reportPersonsJoinModeUpdated(mode)
    }

    return (
        <>
            <p>
                Choose how persons are joined to events. Do not change this setting unless you know what you are doing.
            </p>
            <LemonRadio value={personsJoinMode} onChange={setPersonsJoinMode} options={personsJoinOptions} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(personsJoinMode)}
                    disabledReason={personsJoinMode === savedPersonsJoinMode ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
