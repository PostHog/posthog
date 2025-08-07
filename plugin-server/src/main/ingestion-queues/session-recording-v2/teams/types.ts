import { TeamId } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { RetentionPeriod } from '../types'

export interface TeamForReplay {
    teamId: TeamId
    retentionPeriod: RetentionPeriod
    consoleLogIngestionEnabled: boolean
}

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
