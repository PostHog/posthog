import { createDecipheriv } from 'node:crypto'
import { compressSync } from 'snappy'

import { ML_BLOCK_COMPRESSION } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-compression'
import { compressBlock } from '~/ingestion/pipelines/sessionreplay/sessions/block-compression'

import {
    MlDataKey,
    TAG_BYTES,
    canonicalJson,
    encryptEnvelope,
    encryptEnvelopeJson,
    openSessionKey,
    sealSessionKey,
} from './crypto'
import vector from './encryption-vector.json'
import { TrainingEncryptionVector, decryptEnvelope, decryptEnvelopeFrame } from './envelope-testing'
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
    it.each(['metadata', 'replay-index'])('binds %s parquet values to their purpose and owner', (kind) => {
        const data = Buffer.from('private test payload')
        const envelope = encryptEnvelopeJson(key, kind, data)
        expect(JSON.stringify(envelope)).not.toContain(data.toString())
        expect(decryptEnvelope(key, envelope, kind)).toEqual(data)
        expect(() => decryptEnvelope(key, envelope, 'wrong-purpose')).toThrow()
        expect(() => decryptEnvelope({ ...key, identity: { ...key.identity, teamId: 8 } }, envelope, kind)).toThrow()
        expect(() => decryptEnvelope(key, { ...envelope, context: { ...envelope.context, teamId: 8 } }, kind)).toThrow()
        const corrupted = Buffer.from(envelope.ciphertext, 'base64')
        corrupted[0] ^= 1
        expect(() => decryptEnvelope(key, { ...envelope, ciphertext: corrupted.toString('base64') }, kind)).toThrow()
    })

    it.each(['rrweb', 'image-source', 'image-frontier', 'image-shard', 'image-index', 'score'])(
        'binds %s frames to their purpose and owner',
        (kind) => {
            const data = Buffer.from('private test payload')
            const frame = encryptEnvelope(key, kind, data, { codec: 'none' })
            expect(frame.subarray(0, 6).toString()).toBe('AISR03')
            expect(frame.toString('latin1')).not.toContain(data.toString())
            expect(decryptEnvelopeFrame(key, frame, kind, { codec: 'none' })).toEqual(data)
            expect(() => decryptEnvelopeFrame(key, frame, 'wrong-purpose', { codec: 'none' })).toThrow()
            expect(() =>
                decryptEnvelopeFrame({ ...key, identity: { ...key.identity, teamId: 8 } }, frame, kind, {
                    codec: 'none',
                })
            ).toThrow()
            // The codec is inside the signed context, so a reader cannot be talked out of expanding the body.
            expect(() => decryptEnvelopeFrame(key, frame, kind, { codec: 'brotli' })).toThrow()
            const corrupted = Buffer.from(frame)
            corrupted[corrupted.length - TAG_BYTES - 1] ^= 1
            expect(() => decryptEnvelopeFrame(key, corrupted, kind, { codec: 'none' })).toThrow()
        }
    )

    it('stores far fewer bytes than the snappy and base64 form it replaces', async () => {
        const events = Array.from({ length: 600 }, (_, i) => [
            'w1',
            {
                type: 3,
                timestamp: 1789740000000 + i * 40,
                data: { source: 1, positions: [{ x: i % 700, id: i % 400 }] },
            },
        ])
        const raw = Buffer.from(events.map((event) => JSON.stringify(event)).join('\n'))
        const framed = encryptEnvelope(key, 'rrweb', await compressBlock(raw, ML_BLOCK_COMPRESSION), {
            codec: ML_BLOCK_COMPRESSION.codec,
        })
        const previous = Buffer.from(JSON.stringify(encryptEnvelopeJson(key, 'rrweb', compressSync(raw) as Buffer)))
        expect(framed.length).toBeLessThan(previous.length / 2)
    })

    it('returns the original bytes through the compressor the recorder uses', async () => {
        const data = Buffer.from(JSON.stringify(Array.from({ length: 400 }, (_, i) => ({ row: i, label: 'repeated' }))))
        const frame = encryptEnvelope(key, 'rrweb', await compressBlock(data, ML_BLOCK_COMPRESSION), {
            codec: ML_BLOCK_COMPRESSION.codec,
        })
        expect(frame.length).toBeLessThan(data.length / 4)
        expect(decryptEnvelopeFrame(key, frame, 'rrweb', { codec: ML_BLOCK_COMPRESSION.codec })).toEqual(data)
    })

    it('binds image months to the encrypted session start month', () => {
        const timestamp = Date.parse('2026-09-30T23:59:59.999Z').toString(16).padStart(12, '0')
        const sessionKey = {
            ...key,
            identity: {
                ...key.identity,
                sessionId: `${timestamp.slice(0, 8)}-${timestamp.slice(8)}-7000-8000-000000000007`,
            },
        }
        const ref = `imageurl:v3:${key.identity.teamId}:2026-09:aaaaaaaaaaaaaaaaaaaaaa`
        expect(() => validateImageOwner(ref, sessionKey)).not.toThrow()
        expect(() => validateImageOwner(ref.replace('2026-09', '2026-10'), sessionKey)).toThrow('ownership mismatch')
        expect(() => validateImageOwner(ref.replace(':v3:', ':v2:'), sessionKey)).toThrow('ownership mismatch')
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

    it.each([
        ['truncated', (frame: Buffer) => frame.subarray(0, 100)],
        ['a header shorter than the magic', (frame: Buffer) => frame.subarray(0, 4)],
        [
            'a length that overruns the frame',
            (frame: Buffer) => {
                const overrun = Buffer.from(frame)
                overrun.writeUInt16BE(0xffff, 6)
                return overrun
            },
        ],
    ])('refuses a frame that is %s', (_name, damage) => {
        const frame = Buffer.from(TrainingEncryptionVector.frame.frame, 'base64')
        expect(() =>
            decryptEnvelopeFrame(
                {
                    ...key,
                    identity: TrainingEncryptionVector.context,
                    plaintext: Buffer.from(TrainingEncryptionVector.key, 'base64'),
                },
                damage(frame),
                TrainingEncryptionVector.frame.kind,
                { codec: TrainingEncryptionVector.frame.codec }
            )
        ).toThrow(/Not an ML envelope frame|Invalid authenticated ML envelope/)
    })

    it('opens the shared framed vector, whose pinned parts reassemble into the frame', () => {
        const vector = TrainingEncryptionVector.frame
        const aad = Buffer.from(vector.aad)
        const header = Buffer.allocUnsafe(2)
        header.writeUInt16BE(aad.length)
        expect(vector.aad).toBe(
            canonicalJson({
                v: 3,
                context: { ...TrainingEncryptionVector.context, kind: vector.kind, codec: vector.codec },
            })
        )
        expect(
            Buffer.concat(
                [Buffer.from('AISR03'), header, aad].concat(
                    [vector.nonce, vector.ciphertext, vector.tag].map((part) => Buffer.from(part, 'base64'))
                )
            ).toString('base64')
        ).toBe(vector.frame)
        expect(
            decryptEnvelopeFrame(
                {
                    ...key,
                    identity: TrainingEncryptionVector.context,
                    plaintext: Buffer.from(TrainingEncryptionVector.key, 'base64'),
                },
                Buffer.from(vector.frame, 'base64'),
                vector.kind,
                { codec: vector.codec }
            )
        ).toEqual(Buffer.from(vector.data, 'base64'))
    })

    it('frames the largest fetched image without inflating it', () => {
        const image = Buffer.alloc(20 * 1024 * 1024)
        expect(
            encryptEnvelope(key, 'image-source', image, {
                ref: 'imageurl:v2:7:2026-09:aaaaaaaaaaaaaaaaaaaaaa',
                codec: 'none',
            }).length
        ).toBeLessThan(image.length + 1024)
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

    it('opens the pinned seal, so a reader in another language can check its own bytes', () => {
        const opened = openSessionKey(Buffer.from(vector.seal.teamMonthKey, 'base64'), vector.seal.identity, {
            sealed: Buffer.from(vector.seal.sealedKey, 'base64'),
            nonce: Buffer.from(vector.seal.nonce, 'base64'),
        })
        expect(opened.toString('base64')).toBe(vector.seal.sessionKey)
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
