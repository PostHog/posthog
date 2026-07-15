import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import {
    RetentionResolution,
    RetentionService,
} from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { SessionBatchMetrics } from './sessions/metrics'

jest.mock('~/common/utils/logger', () => ({ logger: { warn: jest.fn() } }))
jest.mock('./sessions/metrics', () => ({
    SessionBatchMetrics: { incrementSessionsDroppedMissingRetention: jest.fn() },
}))

describe('createResolveRetentionStep', () => {
    let mockRetentionService: jest.Mocked<RetentionService>

    // Minimal element carrying just what the step reads (team id, session_id header).
    const element = (teamId: number, sessionId: string): { team: TeamForReplay; headers: SessionReplayHeaders } =>
        ({
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
        }) as unknown as { team: TeamForReplay; headers: SessionReplayHeaders }

    const createStep = () => createResolveRetentionStep(mockRetentionService)

    beforeEach(() => {
        jest.clearAllMocks()
        mockRetentionService = {
            resolveSessionRetentions: jest.fn().mockResolvedValue(new SessionMap<RetentionResolution>()),
        } as unknown as jest.Mocked<RetentionService>
    })

    it('resolves the batch in one call (keyed on the session_id header) and attaches retention', async () => {
        mockRetentionService.resolveSessionRetentions.mockResolvedValue(
            new SessionMap<RetentionResolution>()
                .set(1, 'a', { resolved: true, retentionPeriod: '30d' })
                .set(2, 'b', { resolved: true, retentionPeriod: '1y' })
        )
        const step = createStep()

        const results = await step([element(1, 'a'), element(2, 'b')])

        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledTimes(1)
        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(
            new SessionSet().add(1, 'a').add(2, 'b')
        )
        expect(results.map((r) => (isOkResult(r) ? r.value.retentionPeriod : null))).toEqual(['30d', '1y'])
        expect(SessionBatchMetrics.incrementSessionsDroppedMissingRetention).not.toHaveBeenCalled()
    })

    it('collapses a repeated session into a single resolve, fanned back out to every message', async () => {
        mockRetentionService.resolveSessionRetentions.mockResolvedValue(
            new SessionMap<RetentionResolution>().set(1, 'a', { resolved: true, retentionPeriod: '30d' })
        )
        const step = createStep()

        const results = await step([element(1, 'a'), element(1, 'a'), element(1, 'a')])

        // The three copies dedupe to one session before the service is asked.
        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(results.map((r) => (isOkResult(r) ? r.value.retentionPeriod : null))).toEqual(['30d', '30d', '30d'])
    })

    it('drops an unresolvable session and keeps the rest', async () => {
        mockRetentionService.resolveSessionRetentions.mockResolvedValue(
            new SessionMap<RetentionResolution>()
                .set(999, 'gone', { resolved: false })
                .set(2, 'ok', { resolved: true, retentionPeriod: '90d' })
        )
        const step = createStep()

        const results = await step([element(999, 'gone'), element(2, 'ok')])

        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(
            new SessionSet().add(999, 'gone').add(2, 'ok')
        )
        // The unresolvable session becomes a DROP; its Kafka offset is still covered — the cycle
        // reducer folds every result's offset into the state the flush commits.
        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(isOkResult(results[1]) ? results[1].value.retentionPeriod : null).toBe('90d')
        expect(SessionBatchMetrics.incrementSessionsDroppedMissingRetention).toHaveBeenCalledTimes(1)
    })

    it('propagates a transient failure so the retry wrapper can retry the whole step', async () => {
        mockRetentionService.resolveSessionRetentions.mockRejectedValue(new Error('Redis connection lost'))
        const step = createStep()

        await expect(step([element(1, 'a')])).rejects.toThrow('Redis connection lost')
        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(SessionBatchMetrics.incrementSessionsDroppedMissingRetention).not.toHaveBeenCalled()
    })
})
