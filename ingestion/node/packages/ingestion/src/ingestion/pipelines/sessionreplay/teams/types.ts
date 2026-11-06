import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/shared/teams/types'

export type { TeamForReplay }

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
