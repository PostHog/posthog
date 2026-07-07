import { TeamId } from '~/types'

export interface TeamForReplay {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
    /** Whether the team's organization opted into using its data for AI training. */
    aiTrainingOptedIn: boolean
    /** Origins permitted to record (`https://app.example.com`, `https://*.example.com`); the anonymizer collapses these first-party hosts. */
    recordingDomains?: string[] | null
}
