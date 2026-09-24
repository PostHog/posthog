import { RequiredOrganizationAccessSelector } from './RequiredOrganizationAccessSelector'
import { RequiredTeamAccessSelector } from './RequiredTeamAccessSelector'
import type { ScopeAccessSelectorProps } from './types'
import { UserDefinedAccessSelector } from './UserDefinedAccessSelector'

const ScopeAccessSelector = ({
    accessType,
    organizations,
    teams,
    requiredAccessLevel,
    autoSelectFirst = false,
    teamsLoadFailed,
    onReloadTeams,
}: ScopeAccessSelectorProps): JSX.Element => {
    if (requiredAccessLevel === 'organization') {
        return <RequiredOrganizationAccessSelector organizations={organizations} autoSelectFirst={autoSelectFirst} />
    }

    if (requiredAccessLevel === 'team') {
        return (
            <RequiredTeamAccessSelector
                teams={teams}
                organizations={organizations}
                autoSelectFirst={autoSelectFirst}
                teamsLoadFailed={teamsLoadFailed}
                onReloadTeams={onReloadTeams}
            />
        )
    }

    return (
        <UserDefinedAccessSelector
            accessType={accessType}
            organizations={organizations}
            teams={teams}
            teamsLoadFailed={teamsLoadFailed}
            onReloadTeams={onReloadTeams}
        />
    )
}

export default ScopeAccessSelector
