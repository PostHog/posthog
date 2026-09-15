import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { MAX_STALE_EVENT_DAYS, MIN_STALE_EVENT_DAYS, STALE_EVENT_DAYS, TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { teamLogic } from 'scenes/teamLogic'

export function StaleEventThreshold(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedDays = currentTeam?.data_management_config?.stale_event_days ?? STALE_EVENT_DAYS
    const [days, setDays] = useState<number>(savedDays)
    // The team can arrive after the first render, so the initializer alone leaves the input on the default.
    useEffect(() => {
        setDays(savedDays)
    }, [savedDays])

    const outOfRange = days < MIN_STALE_EVENT_DAYS || days > MAX_STALE_EVENT_DAYS

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                min={MIN_STALE_EVENT_DAYS}
                max={MAX_STALE_EVENT_DAYS}
                step={1}
                value={days}
                onChange={(value) => setDays(Math.round(Number(value) || 0))}
                className="w-24"
                suffix={<span className="text-secondary">days</span>}
                disabledReason={restrictionReason}
                data-attr="stale-event-threshold-days"
            />
            <LemonButton
                type="primary"
                loading={currentTeamLoading}
                onClick={() => updateCurrentTeam({ data_management_config: { stale_event_days: days } })}
                disabledReason={
                    restrictionReason ||
                    (outOfRange
                        ? `Pick a number of days between ${MIN_STALE_EVENT_DAYS} and ${MAX_STALE_EVENT_DAYS}`
                        : days === savedDays
                          ? 'No changes to save'
                          : undefined)
                }
                data-attr="stale-event-threshold-save"
            >
                Save
            </LemonButton>
        </div>
    )
}
