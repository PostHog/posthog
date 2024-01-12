import { organizationLogic } from 'scenes/organizationLogic'

import { teamLogic } from '../../scenes/teamLogic'
import { OrganizationType, TeamType } from '../../types'
import { getAppContext } from './getAppContext'

export function getCurrentTeamId(providedMaybeTeamId?: TeamType['id'] | null): TeamType['id'] {
    const maybeTeamId = providedMaybeTeamId !== undefined ? providedMaybeTeamId : teamLogic.values.currentTeamId
    if (!maybeTeamId) {
        throw new Error(`Project ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeTeamId
}

export function getCurrentOrganizationId(providedMaybeOrgId?: OrganizationType['id'] | null): OrganizationType['id'] {
    const maybeOrgId =
        providedMaybeOrgId !== undefined ? providedMaybeOrgId : organizationLogic.values.currentOrganization?.id
    if (!maybeOrgId) {
        throw new Error(`Organization ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeOrgId
}
