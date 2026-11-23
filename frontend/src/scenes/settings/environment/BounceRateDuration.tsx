import { useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconX } from '@posthog/icons'
import { Button, NumberFieldGroup, NumberFieldInput, NumberFieldRoot } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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

    const handleDurationChange = (x: number | null | undefined): void => {
        if (x == null || Number.isNaN(x)) {
            setBounceRateDuration(DEFAULT_BOUNCE_RATE_DURATION)
        } else {
            setBounceRateDuration(x)
        }
    }

    const handleClear = (e: React.MouseEvent): void => {
        e.stopPropagation()
        setBounceRateDuration(DEFAULT_BOUNCE_RATE_DURATION)
        inputRef.current?.focus()
    }

    const saveDisabledReason =
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

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-4">
                <div className="flex items-center gap-1">
                    <NumberFieldRoot
                        className="w-24"
                        value={bounceRateDuration}
                        onValueChange={handleDurationChange}
                        min={MIN_BOUNCE_RATE_DURATION}
                        max={MAX_BOUNCE_RATE_DURATION}
                        allowOutOfRange
                        disabledReason={restrictedReason}
                    >
                        <NumberFieldGroup>
                            <NumberFieldInput ref={inputRef} aria-label="Bounce rate duration in seconds" />
                        </NumberFieldGroup>
                    </NumberFieldRoot>
                    <Button
                        size="icon"
                        aria-label="Clear input"
                        tooltip="Clear input"
                        onClick={handleClear}
                        disabledReason={restrictedReason}
                    >
                        <IconX />
                    </Button>
                </div>
                <Button
                    variant="primary"
                    onClick={() => handleChange(bounceRateDuration)}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <LemonInput
                type="number"
                min={MIN_BOUNCE_RATE_DURATION}
                max={MAX_BOUNCE_RATE_DURATION}
                value={bounceRateDuration ?? null}
                onChange={handleDurationChange}
                inputRef={inputRef}
                suffix={
                    <LemonButton size="small" noPadding icon={<IconX />} tooltip="Clear input" onClick={handleClear} />
                }
                disabledReason={restrictedReason}
            />
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    onClick={() => handleChange(bounceRateDuration)}
                    disabledReason={saveDisabledReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
