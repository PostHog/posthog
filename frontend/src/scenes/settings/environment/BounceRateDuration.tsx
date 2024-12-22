import { IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import React, { useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

const MIN_BOUNCE_RATE_DURATION = 1
const MAX_BOUNCE_RATE_DURATION = 120

export function BounceRateDurationSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)

    const savedDuration =
        currentTeam?.modifiers?.bounceRateDurationSeconds ?? currentTeam?.default_modifiers?.bounceRateDurationSeconds
    const [bounceRateDuration, setBounceRateDuration] = useState<number | undefined>(savedDuration)

    const handleChange = (duration: number | undefined): void => {
        if (Number.isNaN(duration)) {
            duration = undefined
        }
        updateCurrentTeam({
            modifiers: { ...currentTeam?.modifiers, bounceRateDurationSeconds: duration },
        })
    }

    const inputRef = React.useRef<HTMLInputElement>(null)

    return (
        <>
            <p>
                Choose how long a user can stay on a page, in seconds, before the session is not a bounce. Leave blank
                to use the default of 10 seconds, or set a custom value between 1 second and 120 seconds inclusive.
            </p>
            <LemonInput
                type="number"
                min={MIN_BOUNCE_RATE_DURATION}
                max={MAX_BOUNCE_RATE_DURATION}
                value={bounceRateDuration ?? null}
                onChange={(x) => {
                    if (x == null || Number.isNaN(x)) {
                        setBounceRateDuration(undefined)
                    } else {
                        setBounceRateDuration(x)
                    }
                }}
                inputRef={inputRef}
                suffix={
                    <LemonButton
                        size="small"
                        noPadding
                        icon={<IconX />}
                        tooltip="Clear input"
                        onClick={(e) => {
                            e.stopPropagation()
                            setBounceRateDuration(undefined)
                            inputRef.current?.focus()
                        }}
                    />
                }
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(bounceRateDuration)}
                    disabledReason={
                        bounceRateDuration === savedDuration
                            ? 'No changes to save'
                            : bounceRateDuration == undefined
                            ? undefined
                            : isNaN(bounceRateDuration)
                            ? 'Invalid number'
                            : bounceRateDuration < MIN_BOUNCE_RATE_DURATION
                            ? `Duration must be at least ${MIN_BOUNCE_RATE_DURATION} second`
                            : bounceRateDuration > MAX_BOUNCE_RATE_DURATION
                            ? `Duration must be less than ${MAX_BOUNCE_RATE_DURATION} seconds`
                            : undefined
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
