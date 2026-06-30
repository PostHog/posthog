import { TeamId } from '~/types'

export interface TeamForReplay {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
    /** Whether the team's organization opted into using its data for AI training. */
    aiTrainingOptedIn: boolean
}
