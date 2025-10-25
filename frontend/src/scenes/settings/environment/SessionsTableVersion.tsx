import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'

type SessionTableVersion = NonNullable<HogQLQueryModifiers['sessionTableVersion']>

const bounceRatePageViewModeOptions: LemonRadioOption<SessionTableVersion>[] = [
    {
        value: 'auto',
        label: (
            <>
                <div>Auto</div>
            </>
        ),
    },
    {
        value: 'v1',
        label: (
            <>
                <div>Version 1</div>
            </>
        ),
    },
    {
        value: 'v2',
        label: (
            <>
                <div>Version 2</div>
            </>
        ),
    },
    {
        value: 'v3',
        label: (
            <>
                <div>Version 3</div>
            </>
        ),
    },
]

export function SessionsTableVersion(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const { reportSessionTableVersionUpdated } = useActions(eventUsageLogic)

    const savedSessionTableVersion =
        currentTeam?.modifiers?.sessionTableVersion ?? currentTeam?.default_modifiers?.sessionTableVersion ?? 'auto'
    const [sessionTableVersion, setSessionTableVersion] = useState<SessionTableVersion>(savedSessionTableVersion)

    const handleChange = (version: SessionTableVersion): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, sessionTableVersion: version } })
        reportSessionTableVersionUpdated(version)
    }

    return (
        <>
            <p>
                Choose which version of the session table to use. V2 is faster, but requires uuidv7 session ids. Use
                auto unless you know what you're doing.
            </p>
            <LemonRadio
                value={sessionTableVersion}
                onChange={setSessionTableVersion}
                options={bounceRatePageViewModeOptions}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(sessionTableVersion)}
                    disabledReason={sessionTableVersion === savedSessionTableVersion ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
