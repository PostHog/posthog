import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

export function BounceRateDurationSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedDuration =
        currentTeam?.modifiers?.bounceRateDurationSeconds ?? currentTeam?.default_modifiers?.bounceRateDurationSeconds
    const [bounceRateDuration, setBounceRateDuration] = useState<number | undefined>(savedDuration)

    const handleChange = (duration: number | undefined): void => {
        updateCurrentTeam({ modifiers: { ...currentTeam?.modifiers, bounceRateDurationSeconds: duration } })
    }

    return (
        <>
            <p>
                Choose how long a user can stay on a page, in seconds, before the session is not a bounce. The default
                is 10 seconds.
            </p>
            <LemonInput type="number" min={1} max={120} value={bounceRateDuration} onChange={setBounceRateDuration} />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(bounceRateDuration)}
                    disabledReason={bounceRateDuration === savedDuration ? 'No changes to save' : undefined}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
