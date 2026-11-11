import { TeamId } from '@posthog/node-common/types'

export interface TeamForReplay {
    organizationId?: string
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
    /** Whether the team's organization opted into using its data for AI training. */
    aiTrainingOptedIn: boolean
}
