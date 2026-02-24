import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { EitherMembershipLevel, OrganizationMembershipLevel } from 'lib/constants'
import { LemonSelect, LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

export function TeamSettingSelect<T extends string | number>({
    field,
    options,
    defaultValue,
    minimumAccessLevel = OrganizationMembershipLevel.Member,
}: {
    field: keyof TeamType
    options: LemonSelectOption<T>[]
    defaultValue: T
    minimumAccessLevel?: EitherMembershipLevel
}): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const restrictionReason = useRestrictedArea({ minimumAccessLevel })

    const currentValue = currentTeam?.[field] != null ? (currentTeam[field] as T) : defaultValue

    const handleChange = (value: T | null): void => {
        if (value === null) {
            return
        }
        updateCurrentTeam({ [field]: value } as Partial<TeamType>)
    }

    return (
        <LemonSelect
            value={currentValue}
            onChange={handleChange}
            options={options}
            disabledReason={restrictionReason || (currentTeamLoading ? 'Loading...' : undefined)}
        />
    )
}
