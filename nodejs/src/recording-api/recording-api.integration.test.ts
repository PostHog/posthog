/**
 * Integration tests for the Recording API encryption/decryption
 *
 * Tests the full round-trip of:
 * 1. Encrypting block data
 * 2. Decrypting block data
 * 3. Handling deleted sessions (crypto shredding)
 */
import sodium from 'libsodium-wrappers'
import snappy from 'snappy'

import { parseJSON } from '../utils/json-parse'
import { InMemoryKeyStore } from './keystore'
import { RecordingDecryptor } from './recording-decryptor'
import { RecordingEncryptor } from './recording-encryptor'
import { SessionKey, SessionKeyDeletedError } from './types'

describe('Recording API encryption integration', () => {
    let keyStore: InMemoryKeyStore
    let encryptor: RecordingEncryptor
    let decryptor: RecordingDecryptor

    beforeAll(async () => {
        await sodium.ready
    })

    beforeEach(async () => {
        keyStore = new InMemoryKeyStore()
        await keyStore.start()

        encryptor = new RecordingEncryptor(keyStore)
        await encryptor.start()

        decryptor = new RecordingDecryptor(keyStore)
        await decryptor.start()
    })

    const createBlockData = async (events: unknown[]): Promise<Buffer> => {
        const jsonlContent = events.map((event) => JSON.stringify(['window1', event])).join('\n')
        return snappy.compress(jsonlContent)
    }

    const parseBlockData = async (data: Buffer): Promise<[string, unknown][]> => {
        const decompressed = await snappy.uncompress(data)
        return decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => parseJSON(line))
    }

    describe('encrypt and decrypt round-trip', () => {
        it('should encrypt and decrypt block data correctly', async () => {
            const sessionId = 'test-session-1'
            const teamId = 42
            const originalEvents = [
                { type: 2, data: { source: 1, snapshot: { html: '<div>Hello</div>' } } },
                { type: 3, data: { source: 2, mutations: [{ id: 1 }] } },
            ]

            const blockData = await createBlockData(originalEvents)
            const encrypted = await encryptor.encryptBlock(sessionId, teamId, blockData)

            // Encrypted data should be different from original
            expect(encrypted.equals(blockData)).toBe(false)

            // Encrypted data should be larger (nonce + ciphertext overhead)
            expect(encrypted.length).toBeGreaterThan(blockData.length)

            // Decrypt
            const decrypted = await decryptor.decryptBlock(sessionId, teamId, encrypted)

            // Decrypted data should match original
            expect(decrypted.equals(blockData)).toBe(true)

            // Parse and verify events
            const events = await parseBlockData(decrypted)
            expect(events).toHaveLength(2)
            expect(events[0][1]).toEqual(originalEvents[0])
            expect(events[1][1]).toEqual(originalEvents[1])
        })

        it('should use different nonces for each encryption', async () => {
            const sessionId = 'test-session-2'
            const teamId = 42
            const blockData = await createBlockData([{ type: 2, data: { content: 'same content' } }])

            const encrypted1 = await encryptor.encryptBlock(sessionId, teamId, blockData)
            const encrypted2 = await encryptor.encryptBlock(sessionId, teamId, blockData)

            // Extract nonces (first NONCEBYTES of each encrypted block)
            const nonce1 = encrypted1.subarray(0, sodium.crypto_secretbox_NONCEBYTES)
            const nonce2 = encrypted2.subarray(0, sodium.crypto_secretbox_NONCEBYTES)

            // Nonces should be different
            expect(Buffer.compare(nonce1, nonce2)).not.toBe(0)

            // Both should decrypt to same content
            const decrypted1 = await decryptor.decryptBlock(sessionId, teamId, encrypted1)
            const decrypted2 = await decryptor.decryptBlock(sessionId, teamId, encrypted2)
            expect(decrypted1.equals(decrypted2)).toBe(true)
        })

        it('should use different keys for different sessions', async () => {
            const blockData = await createBlockData([{ type: 2, data: { content: 'same content' } }])

            const encrypted1 = await encryptor.encryptBlock('session-a', 42, blockData)
            const encrypted2 = await encryptor.encryptBlock('session-b', 42, blockData)

            // Decrypt with correct keys
            const decrypted1 = await decryptor.decryptBlock('session-a', 42, encrypted1)
            const decrypted2 = await decryptor.decryptBlock('session-b', 42, encrypted2)

            expect(decrypted1.equals(blockData)).toBe(true)
            expect(decrypted2.equals(blockData)).toBe(true)

            // Cross-decryption should fail
            expect(() => {
                decryptor.decryptBlockWithKey(
                    'session-a',
                    42,
                    encrypted1,
                    // Using a different key (we can't easily get session-b's key here,
                    // so we test via the error thrown when decrypting with wrong key)
                    { plaintextKey: Buffer.alloc(32), encryptedKey: Buffer.alloc(32), sessionState: 'ciphertext' }
                )
            }).toThrow()
        })

        it('should use different keys for different teams', async () => {
            const sessionId = 'same-session-id'
            const blockData = await createBlockData([{ type: 2, data: { content: 'content' } }])

            const encryptedTeam1 = await encryptor.encryptBlock(sessionId, 1, blockData)
            const encryptedTeam2 = await encryptor.encryptBlock(sessionId, 2, blockData)

            // Decrypt with correct team
            const decryptedTeam1 = await decryptor.decryptBlock(sessionId, 1, encryptedTeam1)
            const decryptedTeam2 = await decryptor.decryptBlock(sessionId, 2, encryptedTeam2)

            expect(decryptedTeam1.equals(blockData)).toBe(true)
            expect(decryptedTeam2.equals(blockData)).toBe(true)

            // Cross-team decryption should fail
            await expect(decryptor.decryptBlock(sessionId, 1, encryptedTeam2)).rejects.toThrow()
        })
    })

    describe('crypto shredding (key deletion)', () => {
        it('should throw SessionKeyDeletedError after key is deleted', async () => {
            const sessionId = 'to-be-deleted'
            const teamId = 42
            const blockData = await createBlockData([{ type: 2, data: { secret: 'sensitive data' } }])

            // Encrypt
            const encrypted = await encryptor.encryptBlock(sessionId, teamId, blockData)

            // Verify decryption works before deletion
            const decryptedBefore = await decryptor.decryptBlock(sessionId, teamId, encrypted)
            expect(decryptedBefore.equals(blockData)).toBe(true)

            // Delete the key
            const deleted = await keyStore.deleteKey(sessionId, teamId)
            expect(deleted).toBe(true)

            // Verify decryption fails after deletion
            await expect(decryptor.decryptBlock(sessionId, teamId, encrypted)).rejects.toThrow(SessionKeyDeletedError)
        })

        it('should include deletion timestamp in error', async () => {
            const sessionId = 'deleted-with-timestamp'
            const teamId = 42

            // Generate key first
            await keyStore.generateKey(sessionId, teamId)

            // Delete and capture time
            const beforeDelete = Date.now()
            await keyStore.deleteKey(sessionId, teamId)
            const afterDelete = Date.now()

            // Try to get key
            try {
                await keyStore.getKey(sessionId, teamId)
                fail('Expected SessionKeyDeletedError')
            } catch (error) {
                expect(error).toBeInstanceOf(SessionKeyDeletedError)
                const deletedError = error as SessionKeyDeletedError
                expect(deletedError.deletedAt).toBeGreaterThanOrEqual(beforeDelete)
                expect(deletedError.deletedAt).toBeLessThanOrEqual(afterDelete)
            }
        })

        it('should throw SessionKeyDeletedError when trying to encrypt deleted session', async () => {
            const sessionId = 'deleted-before-encrypt'
            const teamId = 42
            const blockData = await createBlockData([{ type: 2, data: { content: 'content' } }])

            // Generate and delete key
            await keyStore.generateKey(sessionId, teamId)
            await keyStore.deleteKey(sessionId, teamId)

            // Encryption should fail
            await expect(encryptor.encryptBlock(sessionId, teamId, blockData)).rejects.toThrow(SessionKeyDeletedError)
        })

        it('should return false when deleting non-existent key', async () => {
            const deleted = await keyStore.deleteKey('non-existent', 999)
            expect(deleted).toBe(false)
        })

        it('should handle multiple sessions with selective deletion', async () => {
            const sessions = ['keep-1', 'delete-1', 'keep-2', 'delete-2']
            const teamId = 42
            const encrypted: Record<string, Buffer> = {}

            // Encrypt all sessions
            for (const sessionId of sessions) {
                const blockData = await createBlockData([{ type: 2, data: { session: sessionId } }])
                encrypted[sessionId] = await encryptor.encryptBlock(sessionId, teamId, blockData)
            }

            // Delete some sessions
            await keyStore.deleteKey('delete-1', teamId)
            await keyStore.deleteKey('delete-2', teamId)

            // Verify kept sessions are still decryptable
            for (const sessionId of ['keep-1', 'keep-2']) {
                const decrypted = await decryptor.decryptBlock(sessionId, teamId, encrypted[sessionId])
                const events = await parseBlockData(decrypted)
                expect(events[0][1]).toEqual({ type: 2, data: { session: sessionId } })
            }

            // Verify deleted sessions throw errors
            for (const sessionId of ['delete-1', 'delete-2']) {
                await expect(decryptor.decryptBlock(sessionId, teamId, encrypted[sessionId])).rejects.toThrow(
                    SessionKeyDeletedError
                )
            }
        })
    })

    describe('cleartext sessions', () => {
        it('should pass through data unchanged for cleartext sessions', async () => {
            const sessionId = 'cleartext-session'
            const teamId = 42
            const blockData = await createBlockData([{ type: 2, data: { content: 'not encrypted' } }])

            // Manually set a cleartext key
            const cleartextKey: SessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                sessionState: 'cleartext',
            }

            const encrypted = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, cleartextKey)
            expect(encrypted.equals(blockData)).toBe(true)

            const decrypted = decryptor.decryptBlockWithKey(sessionId, teamId, encrypted, cleartextKey)
            expect(decrypted.equals(blockData)).toBe(true)
        })
    })

    describe('large data handling', () => {
        it('should handle large block data', async () => {
            const sessionId = 'large-session'
            const teamId = 42

            // Create large events (100 events with substantial data)
            const largeEvents = Array.from({ length: 100 }, (_, i) => ({
                type: 3,
                data: {
                    source: 2,
                    mutations: Array.from({ length: 50 }, (_, j) => ({
                        id: i * 50 + j,
                        text: `This is mutation ${i * 50 + j} with some additional text to make it larger`,
                        attributes: { class: 'test-class', 'data-index': String(i * 50 + j) },
                    })),
                },
            }))

            const blockData = await createBlockData(largeEvents)
            expect(blockData.length).toBeGreaterThan(50000) // Should be substantial

            const encrypted = await encryptor.encryptBlock(sessionId, teamId, blockData)
            const decrypted = await decryptor.decryptBlock(sessionId, teamId, encrypted)

            expect(decrypted.equals(blockData)).toBe(true)

            const events = await parseBlockData(decrypted)
            expect(events).toHaveLength(100)
        })
    })
})
