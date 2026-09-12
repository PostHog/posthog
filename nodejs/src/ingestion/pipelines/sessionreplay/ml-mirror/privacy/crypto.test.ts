import { KMSClient } from '@aws-sdk/client-kms'

import { parseJSON } from '~/common/utils/json-parse'

import { MlDataKey, MlKeyEncryption, decryptEnvelope, encryptEnvelope } from './crypto'
import { TrainingEncryptionVector } from './test-vectors'
import { validateImageOwner } from './transport'

const key: MlDataKey = {
    identity: {
        teamId: 7,
        organizationId: '00000000-0000-4000-8000-000000000007',
        sessionId: '01994569-4380-7000-8000-000000000007',
        consentGrantedAt: 1789380000000,
    },
    plaintext: Buffer.alloc(32, 7),
    wrapped: Buffer.from('wrapped-test-key'),
}

describe('ML payload encryption', () => {
    beforeAll(async () => {
        await new MlKeyEncryption({ send: jest.fn() } as unknown as KMSClient, 'test-key').start()
    })

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
        const ref = `imageurl:v2:${key.identity.teamId}:${key.identity.consentGrantedAt}:2026-09:aaaaaaaaaaaaaaaaaaaaaa`
        expect(() => validateImageOwner(ref, sessionKey)).not.toThrow()
        expect(() => validateImageOwner(ref.replace('2026-09', '2026-10'), sessionKey)).toThrow('ownership mismatch')
    })

    it('decrypts the shared Python encryption vector', () => {
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
                'imageurl:v2:7:1789380000000:2026-09:aaaaaaaaaaaaaaaaaaaaaa'
            ).length
        ).toBeLessThan(40 * 1024 * 1024 + 64 * 1024)
    })
})
