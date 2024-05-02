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
        label: 'Deprecated old PoE setting. You probably want to choose one of the other options.',
    },
    {
        value: 'person_id_override_properties_on_events',
        label: 'Use ingestion-time person properties from the events table (faster)',
    },
    {
        value: 'person_id_override_properties_joined',
        label: 'Use current person properties from the persons table (slower)',
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
            <p>
                PostHog keeps track of two types of data: persons and events. Persons have properties that change over
                time, while all events have a fixed timestamp, and can't change retroactively.
            </p>
            <p>
                This setting affects query performance. We save a copy of the event's person's properties on the event
                itself, making it possible to query person properties either as they were during ingestion, or as they
                are now.
            </p>
            <p>
                Querying for person properties as they are now on the persons table takes more compute and memory, as we
                need to merge two large datasets.
            </p>
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
