import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { createResolveSessionKeyStep } from './session-batch-resolve-session-key-step'
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

describe('createResolveSessionKeyStep', () => {
    let mockSessionTracker: jest.Mocked<Pick<SessionTracker, 'hasSeen' | 'markSeen'>>
    let mockSessionFilter: jest.Mocked<Pick<SessionFilter, 'handleNewSession' | 'isBlocked'>>
    let mockKeyStore: jest.Mocked<Pick<KeyStore, 'generateKey' | 'getKey'>>

    // Minimal element carrying just what the step reads (message offset, team, session_id header, retention).
    const element = (
        teamId: number,
        sessionId: string,
        retentionPeriod: RetentionPeriod = '30d',
        partition = 0,
        offset = 0
    ): {
        message: { partition: number; offset: number }
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    } =>
        ({
            message: { partition, offset },
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
        createResolveSessionKeyStep(
            mockSessionTracker as unknown as SessionTracker,
            mockSessionFilter as unknown as SessionFilter,
            mockKeyStore as unknown as KeyStore
        )

    beforeEach(() => {
        jest.clearAllMocks()
        // Default: sessions already seen (existing), so the getKey path runs and nothing is marked.
        mockSessionTracker = {
            hasSeen: jest.fn(mapAll(true)),
            markSeen: jest.fn().mockResolvedValue(undefined),
        }
        mockSessionFilter = {
            handleNewSession: jest.fn().mockResolvedValue(undefined),
            isBlocked: jest.fn(mapAll(false)),
        }
        mockKeyStore = {
            generateKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            getKey: jest.fn().mockResolvedValue(createMockSessionKey()),
        }
    })

    it('generates a key for a new session, rate-limiting it, and marks it seen after', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        const generated = createMockSessionKey({ encryptedKey: Buffer.from('new-key') })
        mockKeyStore.generateKey.mockResolvedValue(generated)
        const step = createStep()

        const results = await step([element(1, 'a', '90d')])

        expect(mockSessionFilter.handleNewSession).toHaveBeenCalledWith(1, 'a')
        // New sessions generate a key whose expiry is the resolved retention.
        expect(mockKeyStore.generateKey).toHaveBeenCalledWith('a', 1, RetentionPeriodToDaysMap['90d'])
        expect(mockKeyStore.getKey).not.toHaveBeenCalled()
        expect(isOkResult(results[0]) ? results[0].value.sessionKey : null).toBe(generated)
        // Marked seen only after the key was generated.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
    })

    it('fetches the existing key for a seen session without rate-limiting or marking it', async () => {
        // Default hasSeen: already seen.
        const existing = createMockSessionKey({ encryptedKey: Buffer.from('existing-key') })
        mockKeyStore.getKey.mockResolvedValue(existing)
        const step = createStep()

        const results = await step([element(1, 'a')])

        expect(mockSessionFilter.handleNewSession).not.toHaveBeenCalled()
        expect(mockKeyStore.getKey).toHaveBeenCalledWith('a', 1)
        expect(mockKeyStore.generateKey).not.toHaveBeenCalled()
        expect(isOkResult(results[0]) ? results[0].value.sessionKey : null).toBe(existing)
        // Nothing new to mark.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet())
    })

    it('runs each session bootstrap once and fans the key out to all of its messages', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        const generated = createMockSessionKey({ encryptedKey: Buffer.from('shared-key') })
        mockKeyStore.generateKey.mockResolvedValue(generated)
        const step = createStep()

        const results = await step([element(1, 'a'), element(1, 'a'), element(1, 'a')])

        // A new session must be rate-limited and keyed exactly once, no matter how many of its
        // messages are in the batch — repeating would over-consume the new-session budget and
        // regenerate the key. hasSeen and markSeen run once each for the whole batch.
        expect(mockSessionTracker.hasSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionFilter.handleNewSession).toHaveBeenCalledTimes(1)
        expect(mockKeyStore.generateKey).toHaveBeenCalledTimes(1)
        expect(mockSessionTracker.markSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet().add(1, 'a'))
        expect(results.map((r) => (isOkResult(r) ? r.value.sessionKey : null))).toEqual([
            generated,
            generated,
            generated,
        ])
    })

    it('keys resolutions by (teamId, sessionId) across a mixed batch', async () => {
        const keyA = createMockSessionKey({ encryptedKey: Buffer.from('key-a') })
        const keyB = createMockSessionKey({ encryptedKey: Buffer.from('key-b') })
        mockKeyStore.getKey.mockImplementation((sessionId: string, teamId: number) =>
            Promise.resolve(teamId === 1 ? keyA : keyB)
        )
        const step = createStep()

        const results = await step([element(1, 'shared'), element(2, 'shared')])

        // Same session id, different teams must not collide.
        expect(results.map((r) => (isOkResult(r) ? r.value.sessionKey : null))).toEqual([keyA, keyB])
    })

    it('drops a blocked session without resolving a key, keeping the rest', async () => {
        mockSessionFilter.isBlocked.mockImplementation((sessions: SessionSet) => {
            const map = new SessionMap<boolean>()
            for (const { teamId, sessionId } of sessions) {
                map.set(teamId, sessionId, sessionId === 'blocked')
            }
            return Promise.resolve(map)
        })
        const step = createStep()

        const results = await step([element(1, 'blocked', '30d', 4, 42), element(1, 'ok')])

        expect(results[0].type).toBe(PipelineResultType.DROP)
        expect(isOkResult(results[1])).toBe(true)
        // A blocked session never resolves a key.
        expect(mockKeyStore.getKey).not.toHaveBeenCalledWith('blocked', 1)
    })

    it('rate-limits then blocks a brand-new session in the same batch, dropping it', async () => {
        // A new session runs handleNewSession (which may block it via its own budget) before the
        // block check — so a new session can be dropped by the block it just tripped. Reordering
        // isBlocked before handleNewSession would regress this.
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        mockSessionFilter.isBlocked.mockImplementation(mapAll(true))
        const step = createStep()

        const results = await step([element(1, 'new-and-blocked', '30d', 2, 7)])

        expect(mockSessionFilter.handleNewSession).toHaveBeenCalledWith(1, 'new-and-blocked')
        expect(results[0].type).toBe(PipelineResultType.DROP)
        // Still marked seen so it isn't rate-limited again next batch.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet().add(1, 'new-and-blocked'))
    })

    it('drops a session whose key has been deleted', async () => {
        mockKeyStore.getKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))
        const step = createStep()

        const results = await step([element(1, 'gone', '30d', 3, 9)])

        expect(results[0].type).toBe(PipelineResultType.DROP)
    })

    it('propagates a keystore failure and leaves the session unseen so the retry regenerates', async () => {
        mockSessionTracker.hasSeen.mockImplementation(mapAll(false))
        mockKeyStore.generateKey.mockRejectedValue(new Error('KMS unavailable'))
        const step = createStep()

        await expect(step([element(1, 'a')])).rejects.toThrow('KMS unavailable')
        // Critically, the session is NOT marked seen — otherwise the retry would fetch a key that was
        // never generated and record cleartext.
        expect(mockSessionTracker.markSeen).not.toHaveBeenCalled()
    })
})
