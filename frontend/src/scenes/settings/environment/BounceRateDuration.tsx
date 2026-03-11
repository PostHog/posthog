import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconX } from '@posthog/icons'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

const MIN_BOUNCE_RATE_DURATION = 1
const MAX_BOUNCE_RATE_DURATION = 120
const DEFAULT_BOUNCE_RATE_DURATION = 10

export function BounceRateDurationSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedDuration =
        currentTeam?.modifiers?.bounceRateDurationSeconds ?? currentTeam?.default_modifiers?.bounceRateDurationSeconds
    const [bounceRateDuration, setBounceRateDuration] = useState<number>(savedDuration ?? DEFAULT_BOUNCE_RATE_DURATION)

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
            <LemonInput
                type="number"
                min={MIN_BOUNCE_RATE_DURATION}
                max={MAX_BOUNCE_RATE_DURATION}
                value={bounceRateDuration ?? null}
                onChange={(x) => {
                    if (x == null || Number.isNaN(x)) {
                        setBounceRateDuration(DEFAULT_BOUNCE_RATE_DURATION)
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
                            setBounceRateDuration(DEFAULT_BOUNCE_RATE_DURATION)
                            inputRef.current?.focus()
                        }}
                    />
                }
                disabledReason={restrictedReason}
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
                                    : restrictedReason
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
