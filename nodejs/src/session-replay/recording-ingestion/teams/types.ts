import { TeamForReplay } from '../../teams/types'
import { ParsedMessageData } from '../kafka/types'

export { TeamForReplay } from '../../teams/types'

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
