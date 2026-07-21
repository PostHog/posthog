import { EmailReputationService } from '../email-reputation.service'
import { BatchEvaluationSummary } from '../types'

// One plan page ≈ pageSize ids (bounded well under Temporal's payload limits); the workflow
// walks pages via nextCursor so the fleet-wide team list never rides one activity result.
export const EVALUATION_PLAN_PAGE_SIZE = 5000

export interface EvaluationPlanPage {
    teamIds: number[]
    nextCursor: number | null
    batchSize: number
    batchDelayMs: number
}

export interface EmailReputationActivities {
    fetchTeamsToEvaluate: (evaluatedAt: string, cursorTeamId: number) => Promise<EvaluationPlanPage>
    evaluateTeamBatch: (teamIds: number[], evaluatedAt: string) => Promise<BatchEvaluationSummary>
}

/**
 * Activity payloads ride Temporal workflow history (~2 MiB cap per payload). Only bounded pages
 * of team ids and counts cross the boundary — metric rows and snapshots stay inside the batch
 * activity.
 */
export function createActivities(
    service: EmailReputationService,
    pacing: { batchSize: number; batchDelayMs: number }
): EmailReputationActivities {
    return {
        fetchTeamsToEvaluate: async (evaluatedAt, cursorTeamId) => {
            const { teamIds, nextCursor } = await service.fetchTeamsToEvaluate(
                evaluatedAt,
                cursorTeamId,
                EVALUATION_PLAN_PAGE_SIZE
            )
            return { teamIds, nextCursor, batchSize: pacing.batchSize, batchDelayMs: pacing.batchDelayMs }
        },
        evaluateTeamBatch: (teamIds, evaluatedAt) => service.evaluateTeamBatch(teamIds, evaluatedAt),
    }
}
