import { PipelineResult, isOkResult } from '~/ingestion/framework/results'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Allowed, NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'
import { createResolveKeyStep } from './session-resolve-key-step'

type Base = {
    team: TeamForReplay
    headers: SessionReplayHeaders
    retentionPeriod: RetentionPeriod
} & NewSessionFlag

describe('createResolveKeyStep', () => {
    let mockKeyStore: jest.Mocked<Pick<KeyStore, 'generateKey' | 'getKey'>>

    // Only allowed sessions reach this step — blocked ones are dropped at the gate upstream.
    const element = (
        teamId: number,
        sessionId: string,
        isNewSession: boolean,
        retentionPeriod: RetentionPeriod = '30d'
    ): Allowed<Base> =>
        ({
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            retentionPeriod,
            isNewSession,
            status: 'allowed',
        }) as unknown as Allowed<Base>

    // Reads the resolved key off an ok, allowed result (blocked/deleted results carry no key).
    const keyOf = (result: PipelineResult<Resolved<Base>>): SessionKey | null =>
        isOkResult(result) && result.value.status === 'allowed' ? result.value.sessionKey : null

    // Reads the verdict status off an ok result.
    const statusOf = (result: PipelineResult<Resolved<Base>>): string | null =>
        isOkResult(result) ? result.value.status : null

    const createStep = () => createResolveKeyStep(mockKeyStore as unknown as KeyStore)

    beforeEach(() => {
        jest.clearAllMocks()
        mockKeyStore = {
            generateKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            getKey: jest.fn().mockResolvedValue(createMockSessionKey()),
        }
    })

    it('generates a key for a new allowed session using the resolved retention', async () => {
        const generated = createMockSessionKey({ encryptedKey: Buffer.from('new-key') })
        mockKeyStore.generateKey.mockResolvedValue(generated)

        const result = await createStep()(element(1, 'a', true, '90d'))

        expect(mockKeyStore.generateKey).toHaveBeenCalledWith('a', 1, RetentionPeriodToDaysMap['90d'])
        expect(mockKeyStore.getKey).not.toHaveBeenCalled()
        expect(keyOf(result)).toBe(generated)
    })

    it('fetches the existing key for a seen allowed session', async () => {
        const existing = createMockSessionKey({ encryptedKey: Buffer.from('existing-key') })
        mockKeyStore.getKey.mockResolvedValue(existing)

        const result = await createStep()(element(1, 'a', false))

        expect(mockKeyStore.getKey).toHaveBeenCalledWith('a', 1)
        expect(mockKeyStore.generateKey).not.toHaveBeenCalled()
        expect(keyOf(result)).toBe(existing)
    })

    it('carries a session whose key has been deleted through, tagged deleted (dropped later)', async () => {
        mockKeyStore.getKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))

        const result = await createStep()(element(1, 'gone', false))

        // Not dropped here — the mark-seen step marks it seen (so it isn't re-counted) then drops it.
        expect(statusOf(result)).toBe('deleted')
        expect(keyOf(result)).toBeNull()
    })

    it('propagates a keystore failure so the retry regenerates rather than recording keyless', async () => {
        mockKeyStore.generateKey.mockRejectedValue(new Error('KMS unavailable'))

        await expect(createStep()(element(1, 'a', true))).rejects.toThrow('KMS unavailable')
    })
})
