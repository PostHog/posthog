import { organizationLogic } from 'scenes/organizationLogic'

import { teamLogic } from '../../scenes/teamLogic'
import { OrganizationType, TeamType } from '../../types'
import { getAppContext } from './getAppContext'

export function getCurrentTeamId(): TeamType['id'] {
    const maybeTeamId = teamLogic.values.currentTeamId
    if (!maybeTeamId) {
        throw new Error(`Project ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeTeamId
}

export function getCurrentOrganizationId(): OrganizationType['id'] {
    const maybeOrgId = organizationLogic.values.currentOrganization?.id
    if (!maybeOrgId) {
        throw new Error(`Organization ID is not known.${getAppContext()?.anonymous ? ' User is anonymous.' : ''}`)
    }
    return maybeOrgId
}
