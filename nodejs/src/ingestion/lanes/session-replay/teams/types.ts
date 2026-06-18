import { ParsedMessageData } from '~/ingestion/lanes/session-replay/kafka/types'
import { TeamForReplay } from '~/ingestion/lanes/session-replay/shared/teams/types'

export type { TeamForReplay }

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
