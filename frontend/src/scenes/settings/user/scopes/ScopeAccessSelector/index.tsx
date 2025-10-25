import { RequiredOrganizationAccessSelector } from './RequiredOrganizationAccessSelector'
import { RequiredTeamAccessSelector } from './RequiredTeamAccessSelector'
import { UserDefinedAccessSelector } from './UserDefinedAccessSelector'
import type { ScopeAccessSelectorProps } from './types'

const ScopeAccessSelector = ({
    accessType,
    organizations,
    teams,
    requiredAccessLevel,
    autoSelectFirst = false,
}: ScopeAccessSelectorProps): JSX.Element => {
    if (requiredAccessLevel === 'organization') {
        return <RequiredOrganizationAccessSelector organizations={organizations} autoSelectFirst={autoSelectFirst} />
    }

    if (requiredAccessLevel === 'team') {
        return (
            <RequiredTeamAccessSelector
                teams={teams || []}
                organizations={organizations}
                autoSelectFirst={autoSelectFirst}
            />
        )
    }

    return <UserDefinedAccessSelector accessType={accessType} organizations={organizations} teams={teams} />
}

export default ScopeAccessSelector
