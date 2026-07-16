import { TeamId } from '~/types'

export interface TeamForReplay {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
    /** Whether the team's organization opted into using its data for AI training. */
    aiTrainingOptedIn: boolean
    /** The team's raw recording-domain and app-URL entries; the anonymizer reduces them to first-party host patterns. */
    firstPartyUrlEntries: string[]
}
