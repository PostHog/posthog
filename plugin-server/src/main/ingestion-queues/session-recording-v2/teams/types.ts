import { TeamId } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'

export interface Team {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
}

export interface MessageWithTeam {
    team: Team
    message: ParsedMessageData
}
