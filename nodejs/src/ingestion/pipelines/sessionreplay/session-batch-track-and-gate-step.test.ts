import { PipelineResult, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'

// A hasSeen()/isBlocked() implementation that answers every queried session with the same value.
const mapAll =
    (value: boolean) =>
    (sessions: SessionSet): Promise<SessionMap<boolean>> => {
        const map = new SessionMap<boolean>()
        for (const { teamId, sessionId } of sessions) {
            map.set(teamId, sessionId, value)
        }
        return Promise.resolve(map)
    }

// Reads (isNewSession, blocked) off an ok result, or null if it isn't ok.
const flags = (
    result: PipelineResult<{ isNewSession: boolean; blocked: boolean }>
): { isNewSession: boolean; blocked: boolean } | null =>
    isOkResult(result) ? { isNewSession: result.value.isNewSession, blocked: result.value.blocked } : null

describe('createTrackAndGateStep', () => {
    let mockSessionTracker: jest.Mocked<Pick<SessionTracker, 'hasSeen'>>
    let mockSessionFilter: jest.Mocked<Pick<SessionFilter, 'handleNewSessions' | 'isBlocked'>>

    const element = (
        teamId: number,
        sessionId: string,
        retentionPeriod: RetentionPeriod = '30d'
    ): {
        message: { partition: number; offset: number }
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    } =>
        ({
            message: { partition: 0, offset: 0 },
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            retentionPeriod,
        }) as unknown as {
            message: { partition: number; offset: number }
            team: TeamForReplay
            headers: SessionReplayHeaders
            retentionPeriod: RetentionPeriod
        }

    const createStep = () =>
        createTrackAndGateStep(
            mockSessionTracker as unknown as SessionTracker,
            mockSessionFilter as unknown as SessionFilter
        )

    beforeEach(() => {
        jest.clearAllMocks()
        mockSessionTracker = { hasSeen: jest.fn(mapAll(true)) }
        mockSessionFilter = {
            handleNewSessions: jest.fn().mockResolvedValue(undefined),
            isBlocked: jest.fn(mapAll(false)),
        }
    })

    it('tags a new, unblocked session as new and rate-limits it', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(flags(results[0])).toEqual({ isNewSession: true, blocked: false })
    })

    it('tags a seen session as existing and does not rate-limit it', async () => {
        // Default hasSeen: already seen.
        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet())
        expect(flags(results[0])).toEqual({ isNewSession: false, blocked: false })
    })

    it('tags a blocked session blocked without dropping it (the mark-seen step drops it later)', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        mockSessionFilter.isBlocked.mockImplementation(mapAll(true))

        const results = await createStep()([element(1, 'a')])

        // Carried through, not dropped — so the mark-seen step can mark it seen before dropping it.
        expect(isOkResult(results[0])).toBe(true)
        expect(flags(results[0])).toEqual({ isNewSession: true, blocked: true })
    })

    it('runs each Redis bootstrap once per batch and fans the flags to every message of a session', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a'), element(1, 'a'), element(1, 'a')])

        expect(mockSessionTracker.hasSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.isBlocked).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(results.map(flags)).toEqual([
            { isNewSession: true, blocked: false },
            { isNewSession: true, blocked: false },
            { isNewSession: true, blocked: false },
        ])
    })

    it('keys new/blocked state by (teamId, sessionId) so identical ids on different teams do not collide', async () => {
        mockSessionTracker.hasSeen.mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, teamId === 2) // team 2's session is seen, team 1's is new
            }
            return Promise.resolve(map)
        })

        const results = await createStep()([element(1, 'shared'), element(2, 'shared')])

        expect(results.map((r) => flags(r)?.isNewSession)).toEqual([true, false])
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'shared'))
    })
})
