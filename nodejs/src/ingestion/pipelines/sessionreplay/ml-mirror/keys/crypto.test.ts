import { createDecipheriv } from 'node:crypto'

import { parseJSON } from '~/common/utils/json-parse'

import { MlDataKey, TAG_BYTES, canonicalJson, encryptEnvelope, openSessionKey, sealSessionKey } from './crypto'
import { TrainingEncryptionVector, decryptEnvelope } from './envelope-testing'
import { wrappingContext } from './schema'
import { validateImageOwner } from './transport'

const key: MlDataKey = {
    identity: {
        teamId: 7,
        organizationId: '00000000-0000-4000-8000-000000000007',
        sessionId: '01994569-4380-7000-8000-000000000007',
    },
    plaintext: Buffer.alloc(32, 7),
    wrapped: Buffer.from('wrapped-test-key'),
}

describe('ML payload encryption', () => {
    it.each(['rrweb', 'metadata', 'image-source', 'image-frontier', 'image-shard', 'image-index', 'score'])(
        'binds %s payloads to their purpose and owner',
        (kind) => {
            const data = Buffer.from('private test payload')
            const encoded = encryptEnvelope(key, kind, data)
            expect(encoded.toString()).not.toContain(data.toString())
            const envelope = parseJSON(encoded.toString())
            expect(decryptEnvelope(key, envelope, kind)).toEqual(data)
            expect(() => decryptEnvelope(key, envelope, 'wrong-purpose')).toThrow()
            expect(() =>
                decryptEnvelope({ ...key, identity: { ...key.identity, teamId: 8 } }, envelope, kind)
            ).toThrow()
            expect(() =>
                decryptEnvelope(key, { ...envelope, context: { ...envelope.context, teamId: 8 } }, kind)
            ).toThrow()
            const corrupted = Buffer.from(envelope.ciphertext, 'base64')
            corrupted[0] ^= 1
            expect(() =>
                decryptEnvelope(key, { ...envelope, ciphertext: corrupted.toString('base64') }, kind)
            ).toThrow()
        }
    )

    it('binds image months to the encrypted session start month', () => {
        const timestamp = Date.parse('2026-09-30T23:59:59.999Z').toString(16).padStart(12, '0')
        const sessionKey = {
            ...key,
            identity: {
                ...key.identity,
                sessionId: `${timestamp.slice(0, 8)}-${timestamp.slice(8)}-7000-8000-000000000007`,
            },
        }
        const ref = `imageurl:v2:${key.identity.teamId}:2026-09:aaaaaaaaaaaaaaaaaaaaaa`
        expect(() => validateImageOwner(ref, sessionKey)).not.toThrow()
        expect(() => validateImageOwner(ref.replace('2026-09', '2026-10'), sessionKey)).toThrow('ownership mismatch')
    })

    it('decrypts the shared encryption vector', () => {
        expect(
            decryptEnvelope(
                {
                    ...key,
                    identity: TrainingEncryptionVector.context,
                    plaintext: Buffer.from(TrainingEncryptionVector.key, 'base64'),
                },
                TrainingEncryptionVector.envelope,
                'rrweb'
            )
        ).toEqual(Buffer.from(TrainingEncryptionVector.data, 'base64'))
    })

    it('fits the largest fetched image in the ML Kafka transport budget', () => {
        expect(
            encryptEnvelope(
                key,
                'image-source',
                Buffer.alloc(20 * 1024 * 1024),
                'imageurl:v2:7:2026-09:aaaaaaaaaaaaaaaaaaaaaa'
            ).length
        ).toBeLessThan(40 * 1024 * 1024 + 64 * 1024)
    })
})

describe('sealing a session key under its team month key', () => {
    const teamMonthKey = Buffer.alloc(32, 9)
    const identity = { teamId: 7, sessionId: '01994569-4380-7000-8000-000000000007' }
    const sessionKey = Buffer.alloc(32, 4)

    it('opens what it seals', () => {
        const sealed = sealSessionKey(teamMonthKey, identity, sessionKey)
        expect(openSessionKey(teamMonthKey, identity, sealed)).toEqual(sessionKey)
    })

    it('uses a fresh nonce for each seal', () => {
        const first = sealSessionKey(teamMonthKey, identity, sessionKey)
        const second = sealSessionKey(teamMonthKey, identity, sessionKey)
        expect(first.nonce).not.toEqual(second.nonce)
        expect(first.sealed).not.toEqual(second.sealed)
    })

    it.each([
        ['another team month key', Buffer.alloc(32, 8), identity],
        ['another session', teamMonthKey, { teamId: 7, sessionId: '01994569-4380-7000-8000-000000000008' }],
        ['another team', teamMonthKey, { teamId: 8, sessionId: identity.sessionId }],
    ])('refuses to open under %s', (_label, key, other) => {
        const sealed = sealSessionKey(teamMonthKey, identity, sessionKey)
        expect(() => openSessionKey(key, other, sealed)).toThrow()
    })

    it('does not seal with the stored key itself, which still seals image data', () => {
        const sealed = sealSessionKey(teamMonthKey, identity, sessionKey)
        const asStoredKey = createDecipheriv('aes-256-gcm', teamMonthKey, sealed.nonce, { authTagLength: TAG_BYTES })
        asStoredKey.setAAD(Buffer.from(canonicalJson(wrappingContext(identity))))
        asStoredKey.setAuthTag(sealed.sealed.subarray(sealed.sealed.length - TAG_BYTES))
        expect(() => {
            asStoredKey.update(sealed.sealed.subarray(0, sealed.sealed.length - TAG_BYTES))
            asStoredKey.final()
        }).toThrow()
    })
})
