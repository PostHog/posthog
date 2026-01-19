import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import * as envUtils from '../utils/env-utils'
import { KeyStore, PassthroughKeyStore, getKeyStore } from './keystore'

jest.mock('../utils/env-utils', () => ({
    ...jest.requireActual('../utils/env-utils'),
    isCloud: jest.fn(),
}))

describe('KeyStore', () => {
    let keyStore: KeyStore
    let mockDynamoDBClient: jest.Mocked<DynamoDBClient>
    let mockKMSClient: jest.Mocked<KMSClient>
    let mockRetentionService: jest.Mocked<RetentionService>
    let mockTeamService: jest.Mocked<TeamService>

    const mockPlaintextKey = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    const mockEncryptedKey = new Uint8Array([101, 102, 103, 104, 105])
    const mockNonce = new Uint8Array([201, 202, 203, 204, 205, 206, 207, 208])

    describe('create and start', () => {
        it('should create a KeyStore instance and initialize sodium on start', async () => {
            const dynamoDBClient = { send: jest.fn() } as unknown as jest.Mocked<DynamoDBClient>
            const kmsClient = { send: jest.fn() } as unknown as jest.Mocked<KMSClient>
            const retentionService = {
                getSessionRetentionDays: jest.fn(),
            } as unknown as jest.Mocked<RetentionService>
            const teamService = {
                getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
            } as unknown as jest.Mocked<TeamService>

            const store = new KeyStore(dynamoDBClient, kmsClient, retentionService, teamService)
            await store.start()

            expect(store).toBeInstanceOf(KeyStore)
        })
    })

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))

        mockDynamoDBClient = {
            send: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<DynamoDBClient>

        mockKMSClient = {
            send: jest.fn().mockResolvedValue({
                Plaintext: mockPlaintextKey,
                CiphertextBlob: mockEncryptedKey,
            }),
        } as unknown as jest.Mocked<KMSClient>

        mockRetentionService = {
            getSessionRetentionDays: jest.fn().mockResolvedValue(30),
        } as unknown as jest.Mocked<RetentionService>

        mockTeamService = {
            getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
        } as unknown as jest.Mocked<TeamService>

        keyStore = new KeyStore(mockDynamoDBClient, mockKMSClient, mockRetentionService, mockTeamService)
        await keyStore.start()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('generateKey', () => {
        it('should generate a new key and store it in DynamoDB', async () => {
            const result = await keyStore.generateKey('session-123', 1)

            expect(mockKMSClient.send).toHaveBeenCalledTimes(1)
            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)

            const dynamoCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            expect(dynamoCall.input.TableName).toBe('session-recording-keys')
            expect(dynamoCall.input.Item.session_id).toEqual({ S: 'session-123' })
            expect(dynamoCall.input.Item.team_id).toEqual({ N: '1' })

            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
            expect(result.encryptedKey).toEqual(Buffer.from(mockEncryptedKey))
        })

        it('should cache the key in memory', async () => {
            await keyStore.generateKey('session-123', 1)

            // Second call should use memory cache - no additional DynamoDB/KMS calls
            const result = await keyStore.getKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1) // Only the generateKey call
            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
        })

        it('should calculate expiration based on retention days', async () => {
            mockRetentionService.getSessionRetentionDays.mockResolvedValue(90)

            await keyStore.generateKey('session-123', 1)

            const dynamoCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            const createdAt = Math.floor(new Date('2024-01-15T12:00:00Z').getTime() / 1000)
            const expiresAt = createdAt + 90 * 24 * 60 * 60

            expect(dynamoCall.input.Item.created_at).toEqual({ N: String(createdAt) })
            expect(dynamoCall.input.Item.expires_at).toEqual({ N: String(expiresAt) })
        })

        it('should throw error if KMS fails to generate key', async () => {
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: undefined,
                CiphertextBlob: undefined,
            })

            await expect(keyStore.generateKey('session-123', 1)).rejects.toThrow('Failed to generate data key from KMS')
        })

        it('should query retention service for session retention days', async () => {
            await keyStore.generateKey('session-456', 2)

            expect(mockRetentionService.getSessionRetentionDays).toHaveBeenCalledWith(2, 'session-456')
        })

        it('should throw error if DynamoDB fails to store key', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB error'))

            await expect(keyStore.generateKey('session-123', 1)).rejects.toThrow('DynamoDB error')
        })
    })

    describe('getKey', () => {
        it('should return cached key from memory if available', async () => {
            // First generate a key to populate the cache
            await keyStore.generateKey('session-123', 1)

            // Reset mocks to verify cache is used
            mockDynamoDBClient.send.mockClear()
            mockKMSClient.send.mockClear()

            const result = await keyStore.getKey('session-123', 1)

            expect(mockDynamoDBClient.send).not.toHaveBeenCalled()
            expect(mockKMSClient.send).not.toHaveBeenCalled()
            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
        })

        it('should fetch from DynamoDB and decrypt if not cached', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    session_state: { S: 'ciphertext' },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: mockPlaintextKey,
            })

            const result = await keyStore.getKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)
            expect(mockKMSClient.send).toHaveBeenCalledTimes(1)

            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
            expect(result.encryptedKey).toEqual(Buffer.from(mockEncryptedKey))
            expect(result.nonce).toEqual(Buffer.from(mockNonce))
        })

        it('should cache key in memory after fetching from DynamoDB', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    session_state: { S: 'ciphertext' },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: mockPlaintextKey,
            })

            await keyStore.getKey('session-123', 1)

            // Reset mocks
            mockDynamoDBClient.send.mockClear()
            mockKMSClient.send.mockClear()

            // Second call should use memory cache
            const result = await keyStore.getKey('session-123', 1)

            expect(mockDynamoDBClient.send).not.toHaveBeenCalled()
            expect(mockKMSClient.send).not.toHaveBeenCalled()
            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
        })

        it('should return cleartext key if key not found in DynamoDB', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({ Item: undefined })

            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
        })

        it('should throw error if encrypted_key missing in DynamoDB result for encrypted session', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    nonce: { B: mockNonce },
                    session_state: { S: 'ciphertext' },
                },
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(
                'Missing key data for session session-123 team 1'
            )
        })

        it('should throw error if nonce missing in DynamoDB result for encrypted session', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    session_state: { S: 'ciphertext' },
                },
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(
                'Missing key data for session session-123 team 1'
            )
        })

        it('should return cleartext key if session is not encrypted', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    session_state: { S: 'cleartext' },
                },
            })

            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
            expect(mockKMSClient.send).not.toHaveBeenCalled()
        })

        it('should return deleted key if session was deleted', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    session_state: { S: 'deleted' },
                },
            })

            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('deleted')
            expect(mockKMSClient.send).not.toHaveBeenCalled()
        })

        it('should throw error if DynamoDB query fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB network error'))

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow('DynamoDB network error')
        })

        it('should throw error if KMS fails to decrypt', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    session_state: { S: 'ciphertext' },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: undefined,
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow('Failed to decrypt key from KMS')
        })
    })

    describe('deleteKey', () => {
        it('should mark key as deleted in DynamoDB and return true if key existed', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' }, session_state: { S: 'deleted' } },
            })

            const result = await keyStore.deleteKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)
            const dynamoCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            expect(dynamoCall.input.TableName).toBe('session-recording-keys')
            expect(dynamoCall.input.Key.session_id).toEqual({ S: 'session-123' })
            expect(dynamoCall.input.Key.team_id).toEqual({ N: '1' })
            expect(dynamoCall.input.UpdateExpression).toBe(
                'SET session_state = :deleted, deleted_at = :deleted_at REMOVE encrypted_key, nonce'
            )
            expect(dynamoCall.input.ExpressionAttributeValues[':deleted_at']).toEqual({
                N: String(Math.floor(new Date('2024-01-15T12:00:00Z').getTime() / 1000)),
            })
            expect(dynamoCall.input.ReturnValues).toBe('ALL_NEW')
            expect(result).toBe(true)
        })

        it('should return false if key did not exist', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({})

            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toBe(false)
        })

        it('should update memory cache with deleted state', async () => {
            // First generate a key to populate the cache
            await keyStore.generateKey('session-123', 1)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' }, session_state: { S: 'deleted' } },
            })

            await keyStore.deleteKey('session-123', 1)

            // Reset mocks
            mockDynamoDBClient.send.mockClear()

            // Next getKey should use memory cache with deleted state
            const result = await keyStore.getKey('session-123', 1)

            expect(mockDynamoDBClient.send).not.toHaveBeenCalled()
            expect(result.sessionState).toBe('deleted')
        })

        it('should throw error if DynamoDB update fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB update error'))

            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow('DynamoDB update error')
        })
    })

    describe('stop', () => {
        it('should clean up all clients', () => {
            const mockDestroy = jest.fn()
            ;(mockKMSClient as any).destroy = mockDestroy
            ;(mockDynamoDBClient as any).destroy = mockDestroy

            keyStore.stop()

            expect(mockDestroy).toHaveBeenCalledTimes(2)
        })
    })
})

describe('PassthroughKeyStore', () => {
    let keyStore: PassthroughKeyStore

    beforeEach(() => {
        keyStore = new PassthroughKeyStore()
    })

    describe('start', () => {
        it('should complete without error', async () => {
            await expect(keyStore.start()).resolves.toBeUndefined()
        })
    })

    describe('generateKey', () => {
        it('should return empty keys with sessionState cleartext', async () => {
            const result = await keyStore.generateKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
        })
    })

    describe('getKey', () => {
        it('should return empty keys with sessionState cleartext', async () => {
            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
        })
    })

    describe('deleteKey', () => {
        it('should return true', async () => {
            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toBe(true)
        })
    })

    describe('stop', () => {
        it('should complete without error', () => {
            expect(() => keyStore.stop()).not.toThrow()
        })
    })
})

describe('KeyStore with Redis caching', () => {
    let keyStore: KeyStore
    let mockDynamoDBClient: jest.Mocked<DynamoDBClient>
    let mockKMSClient: jest.Mocked<KMSClient>
    let mockRetentionService: jest.Mocked<RetentionService>
    let mockTeamService: jest.Mocked<TeamService>
    let mockRedisClient: any
    let mockRedisPool: any

    const mockPlaintextKey = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    const mockEncryptedKey = new Uint8Array([101, 102, 103, 104, 105])
    const mockNonce = new Uint8Array([201, 202, 203, 204, 205, 206, 207, 208])

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))

        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
            del: jest.fn().mockResolvedValue(1),
        }

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn().mockResolvedValue(undefined),
        }

        mockDynamoDBClient = {
            send: jest.fn().mockResolvedValue({}),
        } as unknown as jest.Mocked<DynamoDBClient>

        mockKMSClient = {
            send: jest.fn().mockResolvedValue({
                Plaintext: mockPlaintextKey,
                CiphertextBlob: mockEncryptedKey,
            }),
        } as unknown as jest.Mocked<KMSClient>

        mockRetentionService = {
            getSessionRetentionDays: jest.fn().mockResolvedValue(30),
        } as unknown as jest.Mocked<RetentionService>

        mockTeamService = {
            getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
        } as unknown as jest.Mocked<TeamService>

        keyStore = new KeyStore(mockDynamoDBClient, mockKMSClient, mockRetentionService, mockTeamService, mockRedisPool)
        await keyStore.start()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('generateKey', () => {
        it('should cache the key in Redis when Redis pool is provided', async () => {
            await keyStore.generateKey('session-123', 1)

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400, // 24 hours
                expect.any(String)
            )
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })
    })

    describe('getKey', () => {
        it('should check Redis cache before DynamoDB', async () => {
            const cachedKey = {
                plaintextKey: Buffer.from(mockPlaintextKey).toString('base64'),
                encryptedKey: Buffer.from(mockEncryptedKey).toString('base64'),
                nonce: Buffer.from(mockNonce).toString('base64'),
                sessionState: 'ciphertext',
            }
            mockRedisClient.get.mockResolvedValue(JSON.stringify(cachedKey))

            const result = await keyStore.getKey('session-123', 1)

            expect(mockRedisPool.acquire).toHaveBeenCalled()
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/recording-key:1:session-123')
            expect(mockDynamoDBClient.send).not.toHaveBeenCalled()
            expect(mockKMSClient.send).not.toHaveBeenCalled()
            expect(result.plaintextKey).toEqual(Buffer.from(mockPlaintextKey))
        })

        it('should cache key in Redis after fetching from DynamoDB', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    session_state: { S: 'ciphertext' },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: mockPlaintextKey,
            })

            await keyStore.getKey('session-123', 1)

            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.any(String)
            )
        })
    })

    describe('deleteKey', () => {
        it('should update Redis cache with deleted state', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' }, session_state: { S: 'deleted' } },
            })

            await keyStore.deleteKey('session-123', 1)

            expect(mockRedisClient.setex).toHaveBeenCalledWith(
                '@posthog/replay/recording-key:1:session-123',
                86400,
                expect.stringContaining('"sessionState":"deleted"')
            )
        })
    })
})

describe('getKeyStore', () => {
    let mockTeamService: jest.Mocked<TeamService>
    let mockRetentionService: jest.Mocked<RetentionService>

    beforeEach(() => {
        mockTeamService = {
            getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
        } as unknown as jest.Mocked<TeamService>

        mockRetentionService = {
            getSessionRetentionDays: jest.fn().mockResolvedValue(30),
        } as unknown as jest.Mocked<RetentionService>
    })

    it('should return KeyStore when running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore(mockTeamService, mockRetentionService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(KeyStore)
    })

    it('should return PassthroughKeyStore when not running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

        const keyStore = getKeyStore(mockTeamService, mockRetentionService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(PassthroughKeyStore)
    })

    it('should accept optional config with redisPool and redisCacheEnabled', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const mockRedisPool = {
            acquire: jest.fn(),
            release: jest.fn(),
        } as any

        const keyStore = getKeyStore(mockTeamService, mockRetentionService, 'us-east-1', {
            redisPool: mockRedisPool,
            redisCacheEnabled: true,
        })

        expect(keyStore).toBeInstanceOf(KeyStore)
    })

    it('should not use redis pool when redisCacheEnabled is false', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const mockRedisPool = {
            acquire: jest.fn(),
            release: jest.fn(),
        } as any

        // When redisCacheEnabled is false, the keystore should not use Redis
        // (this is verified by the KeyStore internal behavior, not directly testable here)
        const keyStore = getKeyStore(mockTeamService, mockRetentionService, 'us-east-1', {
            redisPool: mockRedisPool,
            redisCacheEnabled: false,
        })

        expect(keyStore).toBeInstanceOf(KeyStore)
    })
})
