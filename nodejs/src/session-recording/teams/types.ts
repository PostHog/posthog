import { TeamForReplay } from '../../session-replay/teams/types'
import { ParsedMessageData } from '../kafka/types'

export { TeamForReplay } from '../../session-replay/teams/types'

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
