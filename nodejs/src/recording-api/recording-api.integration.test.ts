/**
 * Integration tests for the Recording API encryption/decryption
 *
 * Tests the full round-trip of:
 * 1. Encrypting block data
 * 2. Decrypting block data
 * 3. Handling deleted sessions (crypto shredding)
 *
 * Includes tests with:
 * - MemoryKeyStore (always run)
 * - DynamoDB/KMS via Localstack (run when LOCALSTACK_ENABLED=1)
 *
 * To run localstack tests:
 *   docker-compose up localstack
 *   LOCALSTACK_ENABLED=1 pnpm jest src/recording-api/recording-api.integration.test.ts
 */
import {
    CreateTableCommand,
    DeleteTableCommand,
    DescribeTableCommand,
    DynamoDBClient,
    ResourceNotFoundException,
} from '@aws-sdk/client-dynamodb'
import {
    CreateAliasCommand,
    CreateKeyCommand,
    DeleteAliasCommand,
    DescribeKeyCommand,
    KMSClient,
} from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'
import snappy from 'snappy'

import { parseJSON } from '../utils/json-parse'
import { SodiumRecordingDecryptor, SodiumRecordingEncryptor } from './crypto'
import { DynamoDBKeyStore, MemoryKeyStore } from './keystore'
import { KeyStore, SessionKey, SessionKeyDeletedError } from './types'

// Localstack configuration
const LOCALSTACK_ENDPOINT = 'http://localhost:4566'
const KEYS_TABLE_NAME = 'session-recording-keys'
const KMS_KEY_ALIAS = 'alias/session-replay-master-key'
const shouldRunLocalstackTests = process.env.LOCALSTACK_ENABLED === '1'

// Helper functions shared across all tests
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

describe('Recording API encryption integration', () => {
    beforeAll(async () => {
        await sodium.ready
    })

    /**
     * Shared test suite that runs against any KeyStore implementation
     */
    const runEncryptionTests = (
        getKeyStore: () => KeyStore,
        getEncryptor: () => SodiumRecordingEncryptor,
        getDecryptor: () => SodiumRecordingDecryptor
    ) => {
        describe('encrypt and decrypt round-trip', () => {
            it('should encrypt and decrypt block data correctly', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const sessionId = `test-session-${Date.now()}`
                const teamId = 42
                const originalEvents = [
                    { type: 2, data: { source: 1, snapshot: { html: '<div>Hello</div>' } } },
                    { type: 3, data: { source: 2, mutations: [{ id: 1 }] } },
                ]

                // Generate key first (simulates ingestion creating the key)
                const sessionKey = await keyStore.generateKey(sessionId, teamId)

                const blockData = await createBlockData(originalEvents)
                const encrypted = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)

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
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const sessionId = `test-nonce-${Date.now()}`
                const teamId = 42
                const blockData = await createBlockData([{ type: 2, data: { content: 'same content' } }])

                // Generate key first
                const sessionKey = await keyStore.generateKey(sessionId, teamId)

                const encrypted1 = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
                const encrypted2 = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)

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
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const blockData = await createBlockData([{ type: 2, data: { content: 'same content' } }])
                const timestamp = Date.now()

                // Generate keys for both sessions
                const keyA = await keyStore.generateKey(`session-a-${timestamp}`, 42)
                const keyB = await keyStore.generateKey(`session-b-${timestamp}`, 42)

                const encrypted1 = encryptor.encryptBlockWithKey(`session-a-${timestamp}`, 42, blockData, keyA)
                const encrypted2 = encryptor.encryptBlockWithKey(`session-b-${timestamp}`, 42, blockData, keyB)

                // Decrypt with correct keys
                const decrypted1 = await decryptor.decryptBlock(`session-a-${timestamp}`, 42, encrypted1)
                const decrypted2 = await decryptor.decryptBlock(`session-b-${timestamp}`, 42, encrypted2)

                expect(decrypted1.equals(blockData)).toBe(true)
                expect(decrypted2.equals(blockData)).toBe(true)

                // Cross-decryption should fail (using wrong key)
                expect(() => {
                    decryptor.decryptBlockWithKey(`session-a-${timestamp}`, 42, encrypted1, keyB)
                }).toThrow()
            })

            it('should use different keys for different teams', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const sessionId = `same-session-${Date.now()}`
                const blockData = await createBlockData([{ type: 2, data: { content: 'content' } }])

                // Generate keys for both teams
                const key1 = await keyStore.generateKey(sessionId, 1)
                const key2 = await keyStore.generateKey(sessionId, 2)

                const encryptedTeam1 = encryptor.encryptBlockWithKey(sessionId, 1, blockData, key1)
                const encryptedTeam2 = encryptor.encryptBlockWithKey(sessionId, 2, blockData, key2)

                // Decrypt with correct team
                const decryptedTeam1 = await decryptor.decryptBlock(sessionId, 1, encryptedTeam1)
                const decryptedTeam2 = await decryptor.decryptBlock(sessionId, 2, encryptedTeam2)

                expect(decryptedTeam1.equals(blockData)).toBe(true)
                expect(decryptedTeam2.equals(blockData)).toBe(true)

                // Cross-team decryption should fail
                expect(() => {
                    decryptor.decryptBlockWithKey(sessionId, 1, encryptedTeam2, key1)
                }).toThrow()
            })
        })

        describe('crypto shredding (key deletion)', () => {
            it('should throw SessionKeyDeletedError after key is deleted', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const sessionId = `to-be-deleted-${Date.now()}`
                const teamId = 42
                const blockData = await createBlockData([{ type: 2, data: { secret: 'sensitive data' } }])

                // Generate key first
                const sessionKey = await keyStore.generateKey(sessionId, teamId)

                // Encrypt
                const encrypted = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)

                // Verify decryption works before deletion
                const decryptedBefore = await decryptor.decryptBlock(sessionId, teamId, encrypted)
                expect(decryptedBefore.equals(blockData)).toBe(true)

                // Delete the key
                const deleted = await keyStore.deleteKey(sessionId, teamId)
                expect(deleted).toBe(true)

                // Verify decryption fails after deletion
                await expect(decryptor.decryptBlock(sessionId, teamId, encrypted)).rejects.toThrow(
                    SessionKeyDeletedError
                )
            })

            it('should include deletion timestamp in result', async () => {
                const keyStore = getKeyStore()

                const sessionId = `deleted-with-timestamp-${Date.now()}`
                const teamId = 42

                // Generate key first
                await keyStore.generateKey(sessionId, teamId)

                // Delete and capture time (timestamps are in seconds)
                const beforeDelete = Math.floor(Date.now() / 1000)
                await keyStore.deleteKey(sessionId, teamId)
                const afterDelete = Math.floor(Date.now() / 1000) + 1

                // Get key should return deleted state with timestamp
                const result = await keyStore.getKey(sessionId, teamId)
                expect(result.sessionState).toBe('deleted')
                expect(result.deletedAt).toBeGreaterThanOrEqual(beforeDelete)
                expect(result.deletedAt).toBeLessThanOrEqual(afterDelete)
            })

            it('should throw SessionKeyDeletedError when trying to encrypt deleted session', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()

                const sessionId = `deleted-before-encrypt-${Date.now()}`
                const teamId = 42
                const blockData = await createBlockData([{ type: 2, data: { content: 'content' } }])

                // Generate and delete key
                await keyStore.generateKey(sessionId, teamId)
                await keyStore.deleteKey(sessionId, teamId)

                // Encryption should fail
                await expect(encryptor.encryptBlock(sessionId, teamId, blockData)).rejects.toThrow(
                    SessionKeyDeletedError
                )
            })

            it('should return false when deleting non-existent key', async () => {
                const keyStore = getKeyStore()

                const deleted = await keyStore.deleteKey(`non-existent-${Date.now()}`, 999)
                expect(deleted).toBe(false)
            })

            it('should handle multiple sessions with selective deletion', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const timestamp = Date.now()
                const sessions = [
                    `keep-1-${timestamp}`,
                    `delete-1-${timestamp}`,
                    `keep-2-${timestamp}`,
                    `delete-2-${timestamp}`,
                ]
                const teamId = 42
                const encrypted: Record<string, Buffer> = {}

                // Generate keys and encrypt all sessions
                for (const sessionId of sessions) {
                    const sessionKey = await keyStore.generateKey(sessionId, teamId)
                    const blockData = await createBlockData([{ type: 2, data: { session: sessionId } }])
                    encrypted[sessionId] = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
                }

                // Delete some sessions
                await keyStore.deleteKey(`delete-1-${timestamp}`, teamId)
                await keyStore.deleteKey(`delete-2-${timestamp}`, teamId)

                // Verify kept sessions are still decryptable
                for (const sessionId of [`keep-1-${timestamp}`, `keep-2-${timestamp}`]) {
                    const decrypted = await decryptor.decryptBlock(sessionId, teamId, encrypted[sessionId])
                    const events = await parseBlockData(decrypted)
                    expect(events[0][1]).toEqual({ type: 2, data: { session: sessionId } })
                }

                // Verify deleted sessions throw errors
                for (const sessionId of [`delete-1-${timestamp}`, `delete-2-${timestamp}`]) {
                    await expect(decryptor.decryptBlock(sessionId, teamId, encrypted[sessionId])).rejects.toThrow(
                        SessionKeyDeletedError
                    )
                }
            })
        })

        describe('large data handling', () => {
            it('should handle large block data', async () => {
                const keyStore = getKeyStore()
                const encryptor = getEncryptor()
                const decryptor = getDecryptor()

                const sessionId = `large-session-${Date.now()}`
                const teamId = 42

                // Generate key first
                const sessionKey = await keyStore.generateKey(sessionId, teamId)

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

                const encrypted = encryptor.encryptBlockWithKey(sessionId, teamId, blockData, sessionKey)
                const decrypted = await decryptor.decryptBlock(sessionId, teamId, encrypted)

                expect(decrypted.equals(blockData)).toBe(true)

                const events = await parseBlockData(decrypted)
                expect(events).toHaveLength(100)
            })
        })
    }

    // ============================================================
    // Tests with MemoryKeyStore (always run)
    // ============================================================
    describe('with MemoryKeyStore', () => {
        let keyStore: MemoryKeyStore
        let encryptor: SodiumRecordingEncryptor
        let decryptor: SodiumRecordingDecryptor

        beforeEach(async () => {
            keyStore = new MemoryKeyStore()
            await keyStore.start()

            encryptor = new SodiumRecordingEncryptor(keyStore)
            await encryptor.start()

            decryptor = new SodiumRecordingDecryptor(keyStore)
            await decryptor.start()
        })

        runEncryptionTests(
            () => keyStore,
            () => encryptor,
            () => decryptor
        )

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
    })

    // ============================================================
    // Tests with DynamoDB/KMS via Localstack (run when LOCALSTACK_ENABLED=1)
    // ============================================================
    const describeLocalstack = shouldRunLocalstackTests ? describe : describe.skip

    describeLocalstack('with Localstack (DynamoDB + KMS)', () => {
        let dynamoDBClient: DynamoDBClient
        let kmsClient: KMSClient
        let kmsKeyId: string
        let keyStore: DynamoDBKeyStore
        let encryptor: SodiumRecordingEncryptor
        let decryptor: SodiumRecordingDecryptor

        // Mock services that return predictable values
        const mockTeamService = {
            getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
        }

        const mockRetentionService = {
            getSessionRetentionDays: jest.fn().mockResolvedValue(30),
        }

        async function setupKmsKey(): Promise<void> {
            try {
                const describeResult = await kmsClient.send(new DescribeKeyCommand({ KeyId: KMS_KEY_ALIAS }))
                if (describeResult.KeyMetadata?.KeyId) {
                    kmsKeyId = describeResult.KeyMetadata.KeyId
                    return
                }
            } catch {
                // Alias doesn't exist, create key and alias
            }

            const createKeyResult = await kmsClient.send(
                new CreateKeyCommand({
                    Description: 'Session replay master key for testing',
                    KeyUsage: 'ENCRYPT_DECRYPT',
                })
            )

            kmsKeyId = createKeyResult.KeyMetadata!.KeyId!

            await kmsClient.send(
                new CreateAliasCommand({
                    AliasName: KMS_KEY_ALIAS,
                    TargetKeyId: kmsKeyId,
                })
            )
        }

        async function setupDynamoDBTable(): Promise<void> {
            try {
                await dynamoDBClient.send(new DescribeTableCommand({ TableName: KEYS_TABLE_NAME }))
                await dynamoDBClient.send(new DeleteTableCommand({ TableName: KEYS_TABLE_NAME }))
                await waitForTableDeletion()
            } catch (error) {
                if (!(error instanceof ResourceNotFoundException)) {
                    throw error
                }
            }

            await dynamoDBClient.send(
                new CreateTableCommand({
                    TableName: KEYS_TABLE_NAME,
                    KeySchema: [
                        { AttributeName: 'session_id', KeyType: 'HASH' },
                        { AttributeName: 'team_id', KeyType: 'RANGE' },
                    ],
                    AttributeDefinitions: [
                        { AttributeName: 'session_id', AttributeType: 'S' },
                        { AttributeName: 'team_id', AttributeType: 'N' },
                    ],
                    BillingMode: 'PAY_PER_REQUEST',
                })
            )

            await waitForTableActive()
        }

        async function waitForTableActive(): Promise<void> {
            for (let i = 0; i < 30; i++) {
                try {
                    const result = await dynamoDBClient.send(new DescribeTableCommand({ TableName: KEYS_TABLE_NAME }))
                    if (result.Table?.TableStatus === 'ACTIVE') {
                        return
                    }
                } catch {
                    // Table not ready yet
                }
                await new Promise((resolve) => setTimeout(resolve, 1000))
            }
            throw new Error('Timeout waiting for DynamoDB table to become active')
        }

        async function waitForTableDeletion(): Promise<void> {
            for (let i = 0; i < 30; i++) {
                try {
                    await dynamoDBClient.send(new DescribeTableCommand({ TableName: KEYS_TABLE_NAME }))
                } catch (error) {
                    if (error instanceof ResourceNotFoundException) {
                        return
                    }
                }
                await new Promise((resolve) => setTimeout(resolve, 1000))
            }
            throw new Error('Timeout waiting for DynamoDB table deletion')
        }

        beforeAll(async () => {
            dynamoDBClient = new DynamoDBClient({
                endpoint: LOCALSTACK_ENDPOINT,
                region: 'us-east-1',
                credentials: { accessKeyId: 'test', secretAccessKey: 'test' },
            })

            kmsClient = new KMSClient({
                endpoint: LOCALSTACK_ENDPOINT,
                region: 'us-east-1',
                credentials: { accessKeyId: 'test', secretAccessKey: 'test' },
            })

            await setupKmsKey()
            await setupDynamoDBTable()
        }, 30000)

        afterAll(async () => {
            try {
                await dynamoDBClient.send(new DeleteTableCommand({ TableName: KEYS_TABLE_NAME }))
            } catch {
                // Ignore
            }

            try {
                await kmsClient.send(new DeleteAliasCommand({ AliasName: KMS_KEY_ALIAS }))
            } catch {
                // Ignore
            }

            dynamoDBClient.destroy()
            kmsClient.destroy()
        })

        beforeEach(async () => {
            mockTeamService.getEncryptionEnabledByTeamId.mockReset()
            mockTeamService.getEncryptionEnabledByTeamId.mockResolvedValue(true)

            keyStore = new DynamoDBKeyStore(
                dynamoDBClient,
                kmsClient,
                mockRetentionService as any,
                mockTeamService as any
            )
            await keyStore.start()

            encryptor = new SodiumRecordingEncryptor(keyStore)
            await encryptor.start()

            decryptor = new SodiumRecordingDecryptor(keyStore)
            await decryptor.start()
        })

        runEncryptionTests(
            () => keyStore,
            () => encryptor,
            () => decryptor
        )

        describe('DynamoDBKeyStore specific', () => {
            it('should generate and retrieve an encrypted key via KMS', async () => {
                const sessionId = `kms-test-${Date.now()}`
                const teamId = 1

                const generatedKey = await keyStore.generateKey(sessionId, teamId)

                expect(generatedKey.sessionState).toBe('ciphertext')
                expect(generatedKey.plaintextKey.length).toBe(sodium.crypto_secretbox_KEYBYTES)
                expect(generatedKey.encryptedKey.length).toBeGreaterThan(0)

                const retrievedKey = await keyStore.getKey(sessionId, teamId)

                expect(retrievedKey.sessionState).toBe('ciphertext')
                expect(retrievedKey.plaintextKey.equals(generatedKey.plaintextKey)).toBe(true)
                expect(retrievedKey.encryptedKey.equals(generatedKey.encryptedKey)).toBe(true)
            })

            it('should generate cleartext key when encryption is disabled', async () => {
                mockTeamService.getEncryptionEnabledByTeamId.mockResolvedValue(false)

                const sessionId = `cleartext-${Date.now()}`
                const teamId = 2

                const generatedKey = await keyStore.generateKey(sessionId, teamId)

                expect(generatedKey.sessionState).toBe('cleartext')
                expect(generatedKey.plaintextKey.length).toBe(0)
                expect(generatedKey.encryptedKey.length).toBe(0)

                const retrievedKey = await keyStore.getKey(sessionId, teamId)
                expect(retrievedKey.sessionState).toBe('cleartext')
            })

            it('should throw SessionKeyDeletedError when deleting already deleted key', async () => {
                const sessionId = `double-delete-${Date.now()}`
                const teamId = 4

                await keyStore.generateKey(sessionId, teamId)
                await keyStore.deleteKey(sessionId, teamId)

                await expect(keyStore.deleteKey(sessionId, teamId)).rejects.toThrow(SessionKeyDeletedError)
            })

            it('should isolate keys between teams', async () => {
                const sessionId = `shared-session-${Date.now()}`
                const team1 = 10
                const team2 = 20

                const key1 = await keyStore.generateKey(sessionId, team1)
                const key2 = await keyStore.generateKey(sessionId, team2)

                expect(key1.plaintextKey.equals(key2.plaintextKey)).toBe(false)

                const retrieved1 = await keyStore.getKey(sessionId, team1)
                const retrieved2 = await keyStore.getKey(sessionId, team2)

                expect(retrieved1.plaintextKey.equals(key1.plaintextKey)).toBe(true)
                expect(retrieved2.plaintextKey.equals(key2.plaintextKey)).toBe(true)
            })

            it('should not affect other teams when deleting a key', async () => {
                const sessionId = `team-isolation-${Date.now()}`
                const team1 = 30
                const team2 = 40

                await keyStore.generateKey(sessionId, team1)
                await keyStore.generateKey(sessionId, team2)

                await keyStore.deleteKey(sessionId, team1)

                const key1 = await keyStore.getKey(sessionId, team1)
                expect(key1.sessionState).toBe('deleted')

                const key2 = await keyStore.getKey(sessionId, team2)
                expect(key2.sessionState).toBe('ciphertext')
            })
        })
    })
})
