import { v7 as uuidv7 } from 'uuid'

import { logger } from '../../utils/logger'
import { CyclotronV2Manager } from '../services/cyclotron-v2'
import {
    HOG_INVOCATION_REPLAY_MAX_COUNT,
    REPLAY_QUEUE_NAME,
    ReplayFunctionKind,
    ReplayJobState,
    ReplayRequest,
} from './replay-job.types'

export interface ReplayJobManagerConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
    depthLimit?: number
}

/**
 * Thin wrapper around `CyclotronV2Manager` for creating replay wrapper jobs.
 *
 * Kept separate from `CyclotronJobQueuePostgresV2` (which marshals the
 * `CyclotronJobInvocation` shape) because the replay job's `state` blob is a
 * `ReplayJobState`, not an invocation. The consumer (`CdpReplayWorkerConsumer`)
 * pulls jobs from the same `cyclotron_jobs` table via its own `CyclotronV2Worker`
 * scoped to `queueName='replay'`.
 */
export class ReplayJobManager {
    private manager: CyclotronV2Manager

    constructor(private config: ReplayJobManagerConfig) {
        this.manager = new CyclotronV2Manager({
            pool: {
                dbUrl: config.dbUrl,
                maxConnections: config.maxConnections,
                idleTimeoutMs: config.idleTimeoutMs,
            },
            depthLimit: config.depthLimit,
        })
    }

    async connect(): Promise<void> {
        await this.manager.connect()
    }

    async disconnect(): Promise<void> {
        await this.manager.disconnect()
    }

    /**
     * Create a new replay wrapper job. Returns the cyclotron job id —
     * downstream callers (the Django API, eventually a status-poll endpoint)
     * use it to look up progress.
     */
    async enqueue(
        teamId: number,
        functionKind: ReplayFunctionKind,
        functionId: string,
        request: ReplayRequest
    ): Promise<string> {
        const initialIds = request.invocation_ids?.slice(0, HOG_INVOCATION_REPLAY_MAX_COUNT)

        const state: ReplayJobState = {
            function_kind: functionKind,
            function_id: functionId,
            request: {
                invocation_ids: request.invocation_ids,
                filter: request.filter,
            },
            progress: {
                queued: 0,
                skipped: 0,
                cursor: request.filter ? undefined : null,
                // Capture the trimmed id slice on creation so by-IDs jobs are
                // self-contained even if the request blob gets edited later.
                remaining_ids: initialIds,
                done: false,
            },
        }

        const jobId = uuidv7()
        await this.manager.createJob({
            id: jobId,
            teamId,
            // function_id on the job row lets the janitor's by-function metrics
            // group replay jobs alongside the invocations they spawn.
            functionId,
            queueName: REPLAY_QUEUE_NAME,
            state: Buffer.from(JSON.stringify(state)),
        })

        logger.info('🎬', 'Enqueued replay job', {
            replay_job_id: jobId,
            team_id: teamId,
            function_kind: functionKind,
            function_id: functionId,
            mode: request.invocation_ids ? 'by_ids' : 'by_filter',
        })

        return jobId
    }
}
