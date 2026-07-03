import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { createTrackAndGateStep } from './session-batch-track-and-gate-step'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'

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
        // Marking seen happens only after the key resolves (createMarkSeenStep), never in this step.
        expect(mockSessionTracker.markSeen).not.toHaveBeenCalled()
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

    it('drops blocked sessions without marking them seen', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        mockSessionFilter.isBlocked.mockImplementation(mapAll(true))

        const results = await createStep()([element(1, 'a'), element(1, 'b')])

        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(results[1].type).toBe(PipelineResultType.DROP)
        // Blocked sessions stay unseen: while blocked they're re-dropped, and once unblocked they're
        // treated as new so they get a key and record encrypted rather than resolving keyless to cleartext.
        expect(mockSessionTracker.markSeen).not.toHaveBeenCalled()
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
