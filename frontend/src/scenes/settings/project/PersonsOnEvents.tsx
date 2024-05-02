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
        label: 'Fastest (v1): Properties: on events, Person ID: on events',
    },
    {
        value: 'person_id_override_properties_on_events',
        label: 'Best (v2): Properties: on events, Person ID: via overrides table',
    },
    {
        value: 'person_id_override_properties_joined',
        label: 'Good (v3): Properties: on person table, Person ID: via overrides table',
    },
    {
        value: 'disabled',
        label: 'Slowest (v0): Properties: on person table, Person ID: via distinct_id table',
    },
]

export function PersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportPoEModeUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const savedPoEMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'
    const [poeMode, setPoeMode] = useState<PoEMode>(savedPoEMode)

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
            <p>
                The "person ID" option affects how we count unique users. If your users can make both anonymous
                (pre-login) and identified (post-login) events, choose "overrides" to link the anonymous events with the
                user. If you only have fully identified users or fully anonymous users, choose "events" for the best
                performance.
            </p>
            <LemonRadio value={poeMode} onChange={setPoeMode} options={poeOptions} />
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
