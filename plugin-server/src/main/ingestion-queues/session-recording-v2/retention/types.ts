import { ParsedMessageData } from '../kafka/types'
import { TeamForReplay } from '../teams/types'
import { RetentionPeriod } from '../types'

export interface MessageWithRetention {
    retentionPeriod: RetentionPeriod
    team: TeamForReplay
    data: ParsedMessageData
}
