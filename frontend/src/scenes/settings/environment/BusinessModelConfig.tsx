import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

type BusinessModel = NonNullable<TeamType['business_model']> | null

const BUSINESS_MODEL_OPTIONS: { value: BusinessModel; label: string }[] = [
    { value: null, label: 'Not specified' },
    { value: 'b2b', label: 'B2B' },
    { value: 'b2c', label: 'B2C' },
    { value: 'other', label: 'Other' },
]

export function BusinessModelConfig({
    id,
}: {
    /** Lets a field label point at the select. */
    id?: string
}): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (value: BusinessModel): void => updateCurrentTeam({ business_model: value })
    const disabledReason = currentTeamLoading ? 'Loading...' : restrictedReason

    if (todayRailNav) {
        return (
            <Select<BusinessModel> value={currentTeam?.business_model || null} onValueChange={handleChange}>
                <SelectTrigger id={id} className="w-full max-w-160" disabledReason={disabledReason}>
                    <SelectValue>
                        {(selected: BusinessModel) =>
                            BUSINESS_MODEL_OPTIONS.find((option) => option.value === selected)?.label
                        }
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {BUSINESS_MODEL_OPTIONS.map((option) => (
                        <SelectItem key={option.value ?? 'none'} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        )
    }

    return (
        <LemonSelect
            value={currentTeam?.business_model || null}
            onChange={handleChange}
            disabledReason={disabledReason}
            fullWidth
            className="max-w-160"
            options={BUSINESS_MODEL_OPTIONS}
        />
    )
}
