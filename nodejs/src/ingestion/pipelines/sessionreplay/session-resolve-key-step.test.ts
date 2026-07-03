import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { createResolveKeyStep } from './session-resolve-key-step'
import { SessionReplayHeaders } from './validate-headers-step'

jest.mock('~/common/utils/logger', () => ({ logger: { debug: jest.fn() } }))

describe('createResolveKeyStep', () => {
    let mockKeyStore: jest.Mocked<Pick<KeyStore, 'generateKey' | 'getKey'>>

    const element = (
        teamId: number,
        sessionId: string,
        isNewSession: boolean,
        retentionPeriod: RetentionPeriod = '30d'
    ): {
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
        isNewSession: boolean
    } =>
        ({
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            retentionPeriod,
            isNewSession,
        }) as unknown as {
            team: TeamForReplay
            headers: SessionReplayHeaders
            retentionPeriod: RetentionPeriod
            isNewSession: boolean
        }

    const createStep = () => createResolveKeyStep(mockKeyStore as unknown as KeyStore)

    beforeEach(() => {
        jest.clearAllMocks()
        mockKeyStore = {
            generateKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            getKey: jest.fn().mockResolvedValue(createMockSessionKey()),
        }
    })

    it('generates a key for a new session using the resolved retention', async () => {
        const generated = createMockSessionKey({ encryptedKey: Buffer.from('new-key') })
        mockKeyStore.generateKey.mockResolvedValue(generated)

        const result = await createStep()(element(1, 'a', true, '90d'))

        expect(mockKeyStore.generateKey).toHaveBeenCalledWith('a', 1, RetentionPeriodToDaysMap['90d'])
        expect(mockKeyStore.getKey).not.toHaveBeenCalled()
        expect(isOkResult(result) ? result.value.sessionKey : null).toBe(generated)
    })

    it('fetches the existing key for a seen session', async () => {
        const existing = createMockSessionKey({ encryptedKey: Buffer.from('existing-key') })
        mockKeyStore.getKey.mockResolvedValue(existing)

        const result = await createStep()(element(1, 'a', false))

        expect(mockKeyStore.getKey).toHaveBeenCalledWith('a', 1)
        expect(mockKeyStore.generateKey).not.toHaveBeenCalled()
        expect(isOkResult(result) ? result.value.sessionKey : null).toBe(existing)
    })

    it('drops a session whose key has been deleted', async () => {
        mockKeyStore.getKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))

        const result = await createStep()(element(1, 'gone', false))

        expect(result.type).toBe(PipelineResultType.DROP)
    })

    it('propagates a keystore failure so the retry regenerates rather than recording keyless', async () => {
        mockKeyStore.generateKey.mockRejectedValue(new Error('KMS unavailable'))

        await expect(createStep()(element(1, 'a', true))).rejects.toThrow('KMS unavailable')
    })
})
