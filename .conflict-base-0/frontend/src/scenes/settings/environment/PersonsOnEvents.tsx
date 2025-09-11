import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

type PoEMode = NonNullable<HogQLQueryModifiers['personsOnEventsMode']>

const POE_OPTIONS: LemonRadioOption<PoEMode>[] = [
    {
        value: 'person_id_override_properties_on_events',
        label: (
            <span className="inline-flex items-center gap-1.5">
                Use person properties from the time of the event<LemonTag>RECOMMENDED</LemonTag>
            </span>
        ),
        description: (
            <>
                Fast queries. If the person property is updated, query results on past data <em>won't</em> change.
            </>
        ),
    },
    {
        value: 'person_id_override_properties_joined',
        label: 'Use person properties as of running the query',
        description: (
            <>
                Slower queries. If the person property is updated, query results on past data <em>will</em> change
                accordingly.
            </>
        ),
    },
    {
        value: 'person_id_no_override_properties_on_events',
        label: 'Use person IDs and person properties from the time of the event',
        description: (
            <>
                Fastest queries,{' '}
                <span className="underline">but funnels and unique user counts will be inaccurate</span>. If the person
                property is updated, query results on past data <em>won't</em> change.
            </>
        ),
    },
]

export function PersonsOnEvents(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportPoEModeUpdated } = useActions(eventUsageLogic)
    const { currentTeam } = useValues(teamLogic)
    const savedPoEMode: PoEMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode ?? 'disabled'
    const [poeMode, setPoeMode] = useState<PoEMode>(savedPoEMode)

    const handleChange = (mode: PoEMode): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, personsOnEventsMode: mode } })
        posthog.capture('user changed personsOnEventsMode setting', { personsOnEventsMode: mode })
        reportPoEModeUpdated(mode)
    }

    return (
        <>
            <p>
                Choose the behavior of person property filters. For the best performance,{' '}
                <strong>we strongly recommend the first option.</strong>{' '}
                <Link
                    to="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
                    target="blank"
                >
                    Learn about the details in our docs.
                </Link>
            </p>
            <LemonRadio value={poeMode} onChange={setPoeMode} options={POE_OPTIONS} />
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
