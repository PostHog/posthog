import { TeamForReplay } from '~/ingestion/lanes/session-replay/shared/teams/types'

import { ParsedMessageData } from '../kafka/types'

export type { TeamForReplay }

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
