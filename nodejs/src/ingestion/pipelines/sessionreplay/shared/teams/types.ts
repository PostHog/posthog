import { TeamId } from '~/types'

export interface TeamForReplay {
    teamId: TeamId
    consoleLogIngestionEnabled: boolean
    /** Whether the team's organization opted into using its data for AI training. */
    aiTrainingOptedIn: boolean
    /** Registrable domains derived from the team's recording domains; the anonymizer collapses these hosts (and their subdomains) as first-party. */
    firstPartyHosts: string[]
}
