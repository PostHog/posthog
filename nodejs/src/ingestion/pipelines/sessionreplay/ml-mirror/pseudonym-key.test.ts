import { PseudonymKeyConfig, pseudonymKeyFingerprint, resolvePseudonymKey } from './pseudonym-key'

const baseConfig = (over: Partial<PseudonymKeyConfig> = {}): PseudonymKeyConfig => ({
    SESSION_RECORDING_ML_PSEUDONYM_SECRET: '',
    SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY: '',
    SESSION_RECORDING_ML_PSEUDONYM_KMS_REGION: '',
    SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: '',
    ...over,
})

describe('ml-mirror pseudonym key', () => {
    describe('pseudonymKeyFingerprint', () => {
        it('is deterministic, 16-hex, and reveals nothing about the key', () => {
            const fp = pseudonymKeyFingerprint('super-secret-key')
            expect(fp).toBe(pseudonymKeyFingerprint('super-secret-key'))
            expect(fp).toMatch(/^[0-9a-f]{16}$/)
            expect(fp).not.toContain('super-secret-key')
            expect(pseudonymKeyFingerprint('other')).not.toBe(fp)
        })
    })

    describe('resolvePseudonymKey', () => {
        const failDecrypt = () => Promise.reject(new Error('KMS should not be called'))

        it('uses the plaintext env secret when no ciphertext is set (local dev)', async () => {
            const key = await resolvePseudonymKey(
                baseConfig({ SESSION_RECORDING_ML_PSEUDONYM_SECRET: 'dev' }),
                failDecrypt
            )
            expect(key).toBe('dev')
        })

        it('prefers the KMS-decrypted key over the plaintext secret', async () => {
            const decrypt = jest.fn().mockResolvedValue(Buffer.from('kms-key-bytes'))
            const key = await resolvePseudonymKey(
                baseConfig({
                    SESSION_RECORDING_ML_PSEUDONYM_SECRET: 'dev',
                    SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY: 'Y2lwaGVy',
                }),
                decrypt
            )
            expect(decrypt).toHaveBeenCalledWith('Y2lwaGVy', '')
            expect((key as Buffer).toString()).toBe('kms-key-bytes')
        })

        it('fails closed when neither a ciphertext nor a plaintext secret is set', async () => {
            await expect(resolvePseudonymKey(baseConfig(), failDecrypt)).rejects.toThrow(
                'SESSION_RECORDING_ML_PSEUDONYM_WRAPPED_KEY or SESSION_RECORDING_ML_PSEUDONYM_SECRET'
            )
        })

        it('passes when the pinned fingerprint matches the resolved key', async () => {
            const fingerprint = pseudonymKeyFingerprint('dev')
            const key = await resolvePseudonymKey(
                baseConfig({
                    SESSION_RECORDING_ML_PSEUDONYM_SECRET: 'dev',
                    SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: fingerprint,
                }),
                failDecrypt
            )
            expect(key).toBe('dev')
        })

        it('fails closed when the pinned fingerprint does not match (rotation guard)', async () => {
            await expect(
                resolvePseudonymKey(
                    baseConfig({
                        SESSION_RECORDING_ML_PSEUDONYM_SECRET: 'rotated-key',
                        SESSION_RECORDING_ML_PSEUDONYM_KEY_FINGERPRINT: pseudonymKeyFingerprint('original-key'),
                    }),
                    failDecrypt
                )
            ).rejects.toThrow('fingerprint mismatch')
        })
    })
})
