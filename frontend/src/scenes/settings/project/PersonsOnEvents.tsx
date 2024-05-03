import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema'

type PoEMode = NonNullable<HogQLQueryModifiers['personsOnEventsMode']>

const poeOptions: LemonRadioOption<PoEMode>[] = [
    {
        value: 'person_id_no_override_properties_on_events',
        label: (
            <>
                <div>Deprecated: Use person ids and properties from the time of the event.</div>
                <div className="text-muted">
                    May show higher unique user counts due to not using latest person ids. You probably want one of the
                    other options.
                </div>
            </>
        ),
    },
    {
        value: 'person_id_override_properties_on_events',
        label: (
            <>
                <div>Use person properties from the time of the event.</div>
                <div className="text-muted">
                    Faster queries. If person property is updated, then query results on past data won't change.
                </div>
            </>
        ),
    },
    {
        value: 'person_id_override_properties_joined',
        label: (
            <>
                <div>Use latest person properties.</div>
                <div className="text-muted">
                    Slower queries. If person property is updated, then query results on past data will change to
                    reflect it.
                </div>
            </>
        ),
    },
]

const deprecatedOption: PoEMode = 'person_id_no_override_properties_on_events'

export function PersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportPoEModeUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const savedPoEMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'
    const [poeMode, setPoeMode] = useState<PoEMode>(savedPoEMode)

    const visibleOptions =
        savedPoEMode === deprecatedOption
            ? poeOptions
            : poeOptions.filter((option) => option.value !== deprecatedOption)

    const handleChange = (mode: PoEMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, personsOnEventsMode: mode } })
        reportPoEModeUpdated(mode)
    }

    return (
        <>
            <p>Choose how to query your event data with person filters.</p>
            <LemonRadio value={poeMode} onChange={setPoeMode} options={visibleOptions} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(poeMode)}
                    disabledReason={poeMode === savedPoEMode ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
