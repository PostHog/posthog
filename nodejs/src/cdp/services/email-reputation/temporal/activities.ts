import { EmailReputationService } from '../email-reputation.service'
import { BatchEvaluationSummary } from '../types'

export interface EvaluationPlan {
    teamIds: number[]
    batchSize: number
    batchDelayMs: number
}

export interface EmailReputationActivities {
    fetchTeamsToEvaluate: (evaluatedAt: string) => Promise<EvaluationPlan>
    evaluateTeamBatch: (teamIds: number[], evaluatedAt: string) => Promise<BatchEvaluationSummary>
}

/**
 * Activity payloads ride Temporal workflow history (~2 MiB cap per payload). Only team ids and
 * counts cross the boundary — metric rows and snapshots stay inside the batch activity.
 */
export function createActivities(
    service: EmailReputationService,
    pacing: { batchSize: number; batchDelayMs: number }
): EmailReputationActivities {
    return {
        fetchTeamsToEvaluate: async (evaluatedAt) => ({
            teamIds: await service.fetchTeamsToEvaluate(evaluatedAt),
            batchSize: pacing.batchSize,
            batchDelayMs: pacing.batchDelayMs,
        }),
        evaluateTeamBatch: (teamIds, evaluatedAt) => service.evaluateTeamBatch(teamIds, evaluatedAt),
    }
}
