import { v7 as uuidv7 } from 'uuid'

import { logger } from '~/common/utils/logger'

import { CyclotronV2Manager } from '../services/cyclotron-v2'
import {
    RERUN_MAX_WINDOW_DAYS,
    RERUN_QUEUE_NAME,
    RerunFunctionKind,
    RerunJobState,
    RerunRequest,
} from './rerun-job.types'

export interface RerunJobManagerConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
    depthLimit?: number
    /** Mirror of the Django serializer cap (HOG_INVOCATION_RERUN_MAX_COUNT env var). */
    maxCount: number
}

/**
 * Thin wrapper around `CyclotronV2Manager` for creating rerun wrapper jobs.
 *
 * Kept separate from `CyclotronJobQueuePostgresV2` (which marshals the
 * `CyclotronJobInvocation` shape) because the rerun job's `state` blob is a
 * `RerunJobState`, not an invocation. The consumer (`CdpRerunWorkerConsumer`)
 * pulls jobs from the same `cyclotron_jobs` table via its own `CyclotronV2Worker`
 * scoped to `queueName='rerun'`.
 */
export class RerunJobManager {
    private manager: CyclotronV2Manager

    constructor(private config: RerunJobManagerConfig) {
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
     * Create a new rerun wrapper job. Returns the cyclotron job id —
     * downstream callers (the Django API, eventually a status-poll endpoint)
     * use it to look up progress.
     */
    async enqueue(
        teamId: number,
        functionKind: RerunFunctionKind,
        functionId: string,
        request: RerunRequest
    ): Promise<string> {
        // Both bounds are required. Window can't exceed the ClickHouse TTL on
        // hog_invocation_results — older data is already gone via part drop.
        const start = new Date(request.filter.window_start)
        const end = new Date(request.filter.window_end)
        if (isNaN(start.getTime()) || isNaN(end.getTime())) {
            throw new Error('window_start and window_end must be valid ISO 8601 timestamps')
        }
        if (end.getTime() <= start.getTime()) {
            throw new Error('window_end must be after window_start')
        }
        const maxWindowMs = RERUN_MAX_WINDOW_DAYS * 24 * 60 * 60 * 1000
        if (end.getTime() - start.getTime() > maxWindowMs) {
            throw new Error(`rerun window cannot exceed ${RERUN_MAX_WINDOW_DAYS} days (TTL on hog_invocation_results)`)
        }

        const trimmedIds = request.filter.invocation_ids?.slice(0, this.config.maxCount)
        const filter = { ...request.filter, invocation_ids: trimmedIds }

        const state: RerunJobState = {
            function_kind: functionKind,
            function_id: functionId,
            request: { filter },
            progress: {
                queued: 0,
                skipped: 0,
                // Keyset cursor on (scheduled_at, invocation_id). undefined =>
                // start from the top of the window.
                cursor: undefined,
                done: false,
            },
        }

        const jobId = uuidv7()
        await this.manager.createJob({
            id: jobId,
            teamId,
            // function_id on the job row lets the janitor's by-function metrics
            // group rerun jobs alongside the invocations they spawn.
            functionId,
            queueName: RERUN_QUEUE_NAME,
            state: Buffer.from(JSON.stringify(state)),
        })

        logger.info('🎬', 'Enqueued rerun job', {
            rerun_job_id: jobId,
            team_id: teamId,
            function_kind: functionKind,
            function_id: functionId,
            mode: trimmedIds ? 'window_ids' : 'window_filter',
            window_start: filter.window_start,
            window_end: filter.window_end,
            requested_ids_count: trimmedIds?.length ?? 0,
        })

        return jobId
    }
}
