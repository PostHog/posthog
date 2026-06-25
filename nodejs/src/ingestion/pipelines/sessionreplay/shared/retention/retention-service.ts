import {
    RetentionPeriod,
    RetentionPeriodToDaysMap,
    ValidRetentionPeriods,
} from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'

function isValidRetentionPeriod(retentionPeriod: string): retentionPeriod is RetentionPeriod {
    return ValidRetentionPeriods.includes(retentionPeriod as RetentionPeriod)
}

export class RetentionService {
    constructor(private teamService: TeamService) {}

    public async getRetentionByTeamId(teamId: TeamId): Promise<RetentionPeriod> {
        const retentionPeriod = await this.teamService.getRetentionPeriodByTeamId(teamId)

        if (retentionPeriod === null) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Unknown team id ${teamId}`)
        }

        if (!isValidRetentionPeriod(retentionPeriod)) {
            RetentionServiceMetrics.incrementLookupErrors()
            throw new Error(`Error during retention period lookup: Got invalid value ${retentionPeriod}`)
        }

        return retentionPeriod
    }

    public async getSessionRetention(teamId: TeamId, _sessionId: string): Promise<RetentionPeriod> {
        return this.getRetentionByTeamId(teamId)
    }

    public async getSessionRetentionDays(teamId: TeamId, _sessionId: string): Promise<number> {
        const retentionPeriod = await this.getRetentionByTeamId(teamId)
        return RetentionPeriodToDaysMap[retentionPeriod]
    }
}
