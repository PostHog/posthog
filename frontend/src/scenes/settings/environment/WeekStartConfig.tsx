import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { teamLogic } from 'scenes/teamLogic'

const WEEK_START_OPTIONS = [
    { value: 0, label: 'Sunday' },
    { value: 1, label: 'Monday' },
]

export function WeekStartConfig({
    displayWarning = true,
    id,
}: {
    displayWarning?: boolean
    /** Lets a field label point at the select. */
    id?: string
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (value: number): void => {
        if (displayWarning) {
            LemonDialog.open({
                title: `Change the first day of the week to ${value === 0 ? 'Sunday' : 'Monday'}?`,
                description: 'Queries grouped by week will need to be recalculated.',
                primaryButton: {
                    children: 'Change week definition',
                    onClick: () => updateCurrentTeam({ week_start_day: value }),
                },
                secondaryButton: { children: 'Cancel' },
            })
        } else {
            updateCurrentTeam({ week_start_day: value })
        }
    }

    if (todayRailNav) {
        return (
            <Select<number>
                value={currentTeam?.week_start_day || 0}
                onValueChange={(next) => next !== null && handleChange(next)}
            >
                <SelectTrigger id={id} className="w-fit min-w-32" disabledReason={restrictedReason}>
                    <SelectValue>
                        {(selected: number) => WEEK_START_OPTIONS.find((option) => option.value === selected)?.label}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {WEEK_START_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        )
    }

    return (
        <LemonSelect
            value={currentTeam?.week_start_day || 0}
            onChange={handleChange}
            options={WEEK_START_OPTIONS}
            disabledReason={restrictedReason}
        />
    )
}
