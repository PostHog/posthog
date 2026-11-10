import { ParsedMessageData } from '@posthog/replay-storage/kafka/types'
import { TeamForReplay } from '@posthog/replay-storage/teams/types'

export type { TeamForReplay }

export interface MessageWithTeam {
    team: TeamForReplay
    message: ParsedMessageData
}
