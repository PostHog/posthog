import { PipelineResult, isDropResult, isOkResult } from '~/ingestion/framework/results'
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

// Reads (isNewSession, status) off an ok result, or null if it isn't ok. Only allowed sessions survive
// the gate — blocked ones are dropped — so an ok result is always allowed.
const flags = (
    result: PipelineResult<{ isNewSession: boolean; status: 'allowed' }, 'session_blocked'>
): { isNewSession: boolean; status: 'allowed' } | null =>
    isOkResult(result) ? { isNewSession: result.value.isNewSession, status: result.value.status } : null

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
            handleNewSessions: jest.fn().mockResolvedValue(new SessionSet()),
            isBlocked: jest.fn(mapAll(false)),
        }
    })

    it('tags a new, unblocked session as new and rate-limits it', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(flags(results[0])).toEqual({ isNewSession: true, status: 'allowed' })
    })

    it('tags a seen session as existing and does not rate-limit it', async () => {
        // Default hasSeen: already seen.
        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet())
        expect(flags(results[0])).toEqual({ isNewSession: false, status: 'allowed' })
    })

    it('drops an already-blocked session without re-charging its team budget', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        mockSessionFilter.isBlocked.mockImplementation(mapAll(true))

        const results = await createStep()([element(1, 'a')])

        // Already on the blocklist, so it is NOT passed to handleNewSessions — a session dropped for its
        // whole life must not drain a token from its team's budget every batch.
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet())
        // Dropped right at the gate: it carries no key, so nothing downstream needs it.
        expect(isDropResult(results[0]) && results[0].reason).toBe('session_blocked')
    })

    it('drops a session blocked in this batch from the set handleNewSessions returns, without a second isBlocked read', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        // Not on the blocklist yet, but this batch's rate-limit trips and blocks it.
        mockSessionFilter.handleNewSessions.mockResolvedValue(new SessionSet().add(1, 'a'))

        const results = await createStep()([element(1, 'a')])

        expect(mockSessionFilter.isBlocked).toHaveBeenCalledTimes(1)
        expect(isDropResult(results[0]) && results[0].reason).toBe('session_blocked')
    })

    it('runs each Redis bootstrap once per batch and fans the flags to every message of a session', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))

        const results = await createStep()([element(1, 'a'), element(1, 'a'), element(1, 'a')])

        expect(mockSessionTracker.hasSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.isBlocked).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSessions).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(results.map(flags)).toEqual([
            { isNewSession: true, status: 'allowed' },
            { isNewSession: true, status: 'allowed' },
            { isNewSession: true, status: 'allowed' },
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
