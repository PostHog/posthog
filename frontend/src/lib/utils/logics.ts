import { teamLogic } from '../../scenes/teamLogic'
import { TeamType } from '../../types'

export function getCurrentTeamId(providedMaybeTeamId?: TeamType['id'] | null): TeamType['id'] {
    const maybeTeamId = providedMaybeTeamId !== undefined ? providedMaybeTeamId : teamLogic.values.currentTeamId
    if (!maybeTeamId) {
        throw new Error('Project ID is not known.')
    }
    return maybeTeamId
}
