import { InternalFetchService } from '~/common/services/internal-fetch'
import { logger, serializeError } from '~/utils/logger'

// Mirrors HogFlowBatchJob.State in products/workflows/backend/models/hog_flow_batch_job
export type HogFlowBatchJobStatus = 'waiting' | 'queued' | 'active' | 'completed' | 'cancelled' | 'failed'

/**
 * Updates the status of a HogFlow batch job via the Django internal API as it moves through the
 * fan-out lifecycle (queued -> active -> completed/failed/cancelled).
 *
 * Calls the internal endpoint authenticated with INTERNAL_API_SECRET. Updates are best-effort: a
 * failure to report status must never crash batch processing, so errors are logged and swallowed.
 */
export class HogFlowBatchJobStatusService {
    constructor(private internalFetchService: InternalFetchService) {}

    async updateStatus(teamId: number, batchJobId: string, status: HogFlowBatchJobStatus): Promise<void> {
        const urlPath = `/api/projects/${teamId}/internal/hog_flows/batch_jobs/${batchJobId}/status` as const

        try {
            const { fetchResponse, fetchError } = await this.internalFetchService.fetch({
                urlPath,
                fetchParams: {
                    method: 'POST',
                    body: JSON.stringify({ status }),
                },
            })

            if (fetchError || !fetchResponse || fetchResponse.status !== 200) {
                logger.error('Failed to update batch HogFlow job status', {
                    status,
                    batchJobId,
                    teamId,
                    httpStatus: fetchResponse?.status,
                    error: fetchError ? serializeError(fetchError) : undefined,
                })
            }
        } catch (error) {
            logger.error('Error updating batch HogFlow job status', {
                error: serializeError(error),
                batchJobId,
                teamId,
                status,
            })
        }
    }
}
