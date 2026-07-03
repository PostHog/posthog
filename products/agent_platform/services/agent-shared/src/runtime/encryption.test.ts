import { EncryptedFields } from './encryption'

// 32-byte UTF-8 keys (raw, not base64) — matches what Django's settings ship.
const K1 = '01234567890123456789012345678901'
const K2 = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'

describe('EncryptedFields', () => {
    it('round-trips a string with a single key', () => {
        const e = new EncryptedFields(K1)
        const ct = e.encrypt('hello world')
        expect(ct).not.toEqual('hello world')
        expect(e.decrypt(ct)).toBe('hello world')
    })

    it('decrypt tries each key in order — supports rotation', () => {
        const old = new EncryptedFields(K1)
        const ct = old.encrypt('secret-v1')
        // After rotation the NEW key is first; old key is left in the list so
        // pre-rotation ciphertext can still be read until everything's rewritten.
        const rotated = new EncryptedFields(`${K2},${K1}`)
        expect(rotated.decrypt(ct)).toBe('secret-v1')
        // New writes use the new key.
        const ct2 = rotated.encrypt('secret-v2')
        expect(rotated.decrypt(ct2)).toBe('secret-v2')
        // The pre-rotation reader can't decode the new-key ciphertext.
        expect(() => old.decrypt(ct2)).toThrow()
    })

    it('throws at construction when no key is configured (fail-fast)', () => {
        expect(() => new EncryptedFields('')).toThrow(/no keys configured/)
    })

    it('decrypt with ignoreDecryptionErrors returns the input on failure', () => {
        const e = new EncryptedFields(K1)
        expect(e.decrypt('not-encrypted', { ignoreDecryptionErrors: true })).toBe('not-encrypted')
    })

    it('decryptJsonEnv: returns {} for null/undefined/empty', () => {
        const e = new EncryptedFields(K1)
        expect(e.decryptJsonEnv(null)).toEqual({})
        expect(e.decryptJsonEnv(undefined)).toEqual({})
        expect(e.decryptJsonEnv('')).toEqual({})
    })

    it('decryptJsonEnv: round-trips a stringified-object env block', () => {
        const e = new EncryptedFields(K1)
        const ct = e.encrypt(JSON.stringify({ FOO: 'bar', N: 42 }))
        expect(e.decryptJsonEnv(ct)).toEqual({ FOO: 'bar', N: '42' })
    })

    it('decryptJsonEnv: rejects non-object payloads (arrays, scalars)', () => {
        const e = new EncryptedFields(K1)
        const arrayCt = e.encrypt(JSON.stringify(['a', 'b']))
        expect(() => e.decryptJsonEnv(arrayCt)).toThrow(/not a JSON object/)
        const scalarCt = e.encrypt(JSON.stringify('plain'))
        expect(() => e.decryptJsonEnv(scalarCt)).toThrow(/not a JSON object/)
    })

    // EncryptedJSONField (per-leaf), as used by mcp_store sensitive_configuration.
    it('encryptJsonFieldValue → decryptJsonFieldValue round-trips object leaves', () => {
        const e = new EncryptedFields(K1)
        const encrypted = e.encryptJsonFieldValue({ access_token: 'tok', nested: { refresh: 'r' } })
        // Structure preserved as plaintext JSON; only leaves are ciphertext.
        const obj = encrypted as Record<string, unknown>
        expect(typeof obj.access_token).toBe('string')
        expect(obj.access_token).not.toBe('tok')
        expect(e.decryptJsonFieldValue(encrypted)).toEqual({ access_token: 'tok', nested: { refresh: 'r' } })
    })

    it('encryptJsonFieldValue str()-ifies scalars like Django (int→"3600", bool→"True"); null passes through', () => {
        const e = new EncryptedFields(K1)
        const decrypted = e.decryptJsonFieldValue(
            e.encryptJsonFieldValue({ expires_in: 3600, needs_reauth: true, off: false, missing: null })
        )
        expect(decrypted).toEqual({ expires_in: '3600', needs_reauth: 'True', off: 'False', missing: null })
    })

    it('decryptJsonFieldValue tolerates a rotated key (new key first, old behind)', () => {
        const old = new EncryptedFields(K1)
        const stored = old.encryptJsonFieldValue({ access_token: 'tok' })
        const rotated = new EncryptedFields(`${K2},${K1}`)
        expect(rotated.decryptJsonFieldValue(stored)).toEqual({ access_token: 'tok' })
    })
})
