import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import {
    RetentionResolution,
    RetentionService,
} from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { createResolveRetentionStep } from './session-batch-resolve-retention-step'
import { SessionBatchMetrics } from './sessions/metrics'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'

jest.mock('~/common/utils/logger', () => ({ logger: { warn: jest.fn() } }))
jest.mock('./sessions/metrics', () => ({
    SessionBatchMetrics: { incrementSessionsDroppedMissingRetention: jest.fn() },
}))

type RetentionElement = {
    message: { partition: number; offset: number }
    team: TeamForReplay
    headers: SessionReplayHeaders
} & SessionBatchContext

describe('createResolveRetentionStep', () => {
    let mockRetentionService: jest.Mocked<RetentionService>
    let mockBatch: jest.Mocked<Pick<SessionBatchRecorder, 'getRetention'>>

    // Minimal element carrying just what the step reads (message offset, team id, session_id header)
    // plus the cycle's recorder, which the accumulating pipeline tags onto every element.
    const element = (teamId: number, sessionId: string, partition = 0, offset = 0): RetentionElement =>
        ({
            message: { partition, offset },
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            sessionBatchRecorder: mockBatch,
        }) as unknown as RetentionElement

    const createStep = () => createResolveRetentionStep(mockRetentionService)

    beforeEach(() => {
        jest.clearAllMocks()
        mockRetentionService = {
            resolveSessionRetentions: jest.fn().mockResolvedValue(new SessionMap<RetentionResolution>()),
        } as unknown as jest.Mocked<RetentionService>
        // Default: no session is already in the batch, so everything is resolved via the service.
        mockBatch = { getRetention: jest.fn().mockReturnValue(undefined) } as unknown as jest.Mocked<
            Pick<SessionBatchRecorder, 'getRetention'>
        >
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

    it('reuses retention already held in the batch and only resolves the unseen sessions', async () => {
        // Session 'a' (team 1) is already in the batch; 'b' (team 2) is not.
        mockBatch.getRetention.mockImplementation((teamId: number) => (teamId === 1 ? '90d' : undefined))
        mockRetentionService.resolveSessionRetentions.mockResolvedValue(
            new SessionMap<RetentionResolution>().set(2, 'b', { resolved: true, retentionPeriod: '1y' })
        )
        const step = createStep()

        const results = await step([element(1, 'a'), element(2, 'b')])

        // Only the unseen session is sent to the service.
        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(new SessionSet().add(2, 'b'))
        expect(results.map((r) => (isOkResult(r) ? r.value.retentionPeriod : null))).toEqual(['90d', '1y'])
    })

    it('sends nothing to the service when every session is already in the batch', async () => {
        mockBatch.getRetention.mockReturnValue('30d')
        const step = createStep()

        const results = await step([element(1, 'a'), element(2, 'b')])

        // Everything came from the batch, so the resolve set is empty (the service no-ops on it).
        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(new SessionSet())
        expect(results.map((r) => (isOkResult(r) ? r.value.retentionPeriod : null))).toEqual(['30d', '30d'])
    })

    it('drops an unresolvable session and keeps the rest', async () => {
        mockRetentionService.resolveSessionRetentions.mockResolvedValue(
            new SessionMap<RetentionResolution>()
                .set(999, 'gone', { resolved: false })
                .set(2, 'ok', { resolved: true, retentionPeriod: '90d' })
        )
        const step = createStep()

        const results = await step([element(999, 'gone', 4, 42), element(2, 'ok')])

        expect(mockRetentionService.resolveSessionRetentions).toHaveBeenCalledWith(
            new SessionSet().add(999, 'gone').add(2, 'ok')
        )
        // The unresolvable session becomes a DROP; its Kafka offset is tracked downstream by the
        // consumer's offset tracking as a record-phase result, not here.
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
