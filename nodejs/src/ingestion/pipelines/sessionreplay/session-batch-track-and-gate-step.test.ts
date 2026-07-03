import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'
import { SessionReplayHeaders } from './validate-headers-step'

jest.mock('~/common/utils/logger', () => ({ logger: { debug: jest.fn() } }))

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

describe('createTrackAndGateStep', () => {
    let mockSessionTracker: jest.Mocked<Pick<SessionTracker, 'hasSeen' | 'markSeen'>>
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
        mockSessionTracker = {
            hasSeen: jest.fn(mapAll(true)),
            markSeen: jest.fn().mockResolvedValue(undefined),
        }
        mockSessionFilter = {
            handleNewSessions: jest.fn().mockResolvedValue(undefined),
            isBlocked: jest.fn(mapAll(false)),
        }
    })

    it('tags a new session as new and rate-limits it', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(isOkResult(results[0]) ? results[0].value.isNewSession : null).toBe(true)
        // A surviving new session is marked seen later (after its key resolves), not here.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet())
    })

    it('tags a seen session as existing and does not rate-limit it', async () => {
        // Default hasSeen: already seen.
        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet())
        expect(isOkResult(results[0]) ? results[0].value.isNewSession : null).toBe(false)
    })

    it('runs each Redis bootstrap once per batch and fans isNewSession to every message of a session', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a'), element(1, 'a'), element(1, 'a')])

        expect(mockSessionTracker.hasSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.isBlocked).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(results.map((r) => (isOkResult(r) ? r.value.isNewSession : null))).toEqual([true, true, true])
    })

    it('drops a blocked session and keeps the rest', async () => {
        mockSessionFilter.isBlocked.mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, sessionId === 'blocked')
            }
            return Promise.resolve(map)
        })

        const results = await createStep()([element(1, 'blocked'), element(1, 'ok')])

        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(isOkResult(results[1])).toBe(true)
    })

    it('marks a blocked NEW session seen but not a blocked EXISTING one', async () => {
        // 'new' is unseen, 'old' is seen; both get blocked.
        mockSessionTracker.hasSeen.mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, sessionId === 'old')
            }
            return Promise.resolve(map)
        })
        mockSessionFilter.isBlocked.mockImplementation(mapAll(true))

        const results = await createStep()([element(1, 'new'), element(1, 'old')])

        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(results[1].type).toBe(PipelineResultType.DROP)
        // Only the blocked NEW session is marked seen here — the blocked existing one already was.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet().add(1, 'new'))
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

        expect(results.map((r) => (isOkResult(r) ? r.value.isNewSession : null))).toEqual([true, false])
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'shared'))
    })
})
