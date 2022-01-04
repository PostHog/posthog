import { teamLogic } from '../../scenes/teamLogic'
import { TeamType } from '../../types'
import { getAppContext } from './getAppContext'

export function getCurrentTeamId(providedMaybeTeamId?: TeamType['id'] | null): TeamType['id'] | null {
    const maybeTeamId = providedMaybeTeamId !== undefined ? providedMaybeTeamId : teamLogic.values.currentTeamId
    if (!maybeTeamId && !getAppContext()?.anonymous) {
        throw new Error('Project ID is not known.')
    }
    return maybeTeamId
}
