import { PipelineResult, PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Gated, NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'
import { createResolveKeyStep } from './session-resolve-key-step'

jest.mock('~/common/utils/logger', () => ({ logger: { debug: jest.fn() } }))

type Base = {
    team: TeamForReplay
    headers: SessionReplayHeaders
    retentionPeriod: RetentionPeriod
} & NewSessionFlag

describe('createResolveKeyStep', () => {
    let mockKeyStore: jest.Mocked<Pick<KeyStore, 'generateKey' | 'getKey'>>

    const element = (
        teamId: number,
        sessionId: string,
        isNewSession: boolean,
        blocked: boolean,
        retentionPeriod: RetentionPeriod = '30d'
    ): Gated<Base> =>
        ({
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            retentionPeriod,
            isNewSession,
            blocked,
        }) as unknown as Gated<Base>

    // Reads the resolved key off an ok, allowed result (blocked results carry no key).
    const keyOf = (result: PipelineResult<Resolved<Base>>): SessionKey | null =>
        isOkResult(result) && !result.value.blocked ? result.value.sessionKey : null

    const createStep = () => createResolveKeyStep(mockKeyStore as unknown as KeyStore)

    beforeEach(() => {
        jest.clearAllMocks()
        mockKeyStore = {
            generateKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            getKey: jest.fn().mockResolvedValue(createMockSessionKey()),
        }
    })

    it('passes a blocked session through without resolving a key', async () => {
        const result = await createStep()(element(1, 'a', true, true))

        expect(mockKeyStore.generateKey).not.toHaveBeenCalled()
        expect(mockKeyStore.getKey).not.toHaveBeenCalled()
        expect(isOkResult(result)).toBe(true)
        expect(keyOf(result)).toBeNull()
    })

    it('generates a key for a new allowed session using the resolved retention', async () => {
        const generated = createMockSessionKey({ encryptedKey: Buffer.from('new-key') })
        mockKeyStore.generateKey.mockResolvedValue(generated)

        const result = await createStep()(element(1, 'a', true, false, '90d'))

        expect(mockKeyStore.generateKey).toHaveBeenCalledWith('a', 1, RetentionPeriodToDaysMap['90d'])
        expect(mockKeyStore.getKey).not.toHaveBeenCalled()
        expect(keyOf(result)).toBe(generated)
    })

    it('fetches the existing key for a seen allowed session', async () => {
        const existing = createMockSessionKey({ encryptedKey: Buffer.from('existing-key') })
        mockKeyStore.getKey.mockResolvedValue(existing)

        const result = await createStep()(element(1, 'a', false, false))

        expect(mockKeyStore.getKey).toHaveBeenCalledWith('a', 1)
        expect(mockKeyStore.generateKey).not.toHaveBeenCalled()
        expect(keyOf(result)).toBe(existing)
    })

    it('drops an allowed session whose key has been deleted', async () => {
        mockKeyStore.getKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))

        const result = await createStep()(element(1, 'gone', false, false))

        expect(result.type).toBe(PipelineResultType.DROP)
    })

    it('propagates a keystore failure so the retry regenerates rather than recording keyless', async () => {
        mockKeyStore.generateKey.mockRejectedValue(new Error('KMS unavailable'))

        await expect(createStep()(element(1, 'a', true, false))).rejects.toThrow('KMS unavailable')
    })
})
