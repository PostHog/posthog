import { TeamId } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'

export interface TeamForReplay {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
}

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
