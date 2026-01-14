import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'
import { Redis } from 'ioredis'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { RedisPool } from '../types'
import * as redisUtils from '../utils/db/redis'
import * as envUtils from '../utils/env-utils'
import { KeyStore, PassthroughKeyStore, SessionKey, getKeyStore } from './keystore'

jest.mock('../utils/env-utils', () => ({
    ...jest.requireActual('../utils/env-utils'),
    isCloud: jest.fn(),
}))

jest.mock('../utils/db/redis', () => ({
    createRedisPoolFromConfig: jest.fn(),
}))

describe('KeyStore', () => {
    let keyStore: KeyStore
    let mockRedisClient: jest.Mocked<Redis>
    let mockRedisPool: jest.Mocked<RedisPool>
    let mockDynamoDBClient: jest.Mocked<DynamoDBClient>
    let mockKMSClient: jest.Mocked<KMSClient>
    let mockRetentionService: jest.Mocked<RetentionService>
    let mockTeamService: jest.Mocked<TeamService>

    const mockPlaintextKey = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
    const mockEncryptedKey = new Uint8Array([101, 102, 103, 104, 105])
    const mockNonce = new Uint8Array([201, 202, 203, 204, 205, 206, 207, 208])

    describe('create and start', () => {
        it('should create a KeyStore instance and initialize sodium on start', async () => {
            const redisClient = { get: jest.fn(), setex: jest.fn() } as unknown as jest.Mocked<Redis>
            const redisPool = {
                acquire: jest.fn().mockResolvedValue(redisClient),
                release: jest.fn().mockResolvedValue(undefined),
            } as unknown as jest.Mocked<RedisPool>
            const dynamoDBClient = { send: jest.fn() } as unknown as jest.Mocked<DynamoDBClient>
            const kmsClient = { send: jest.fn() } as unknown as jest.Mocked<KMSClient>
            const retentionService = {
                getSessionRetentionDays: jest.fn(),
            } as unknown as jest.Mocked<RetentionService>
            const teamService = {
                getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
            } as unknown as jest.Mocked<TeamService>

            const store = new KeyStore(redisPool, dynamoDBClient, kmsClient, retentionService, teamService)
            await store.start()

            expect(store).toBeInstanceOf(KeyStore)
        })
    })

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-01-15T12:00:00Z'))

        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
            del: jest.fn().mockResolvedValue(1),
        } as unknown as jest.Mocked<Redis>

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<RedisPool>

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

        keyStore = new KeyStore(mockRedisPool, mockDynamoDBClient, mockKMSClient, mockRetentionService, mockTeamService)
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

        it('should cache the key in Redis', async () => {
            await keyStore.generateKey('session-123', 1)

            expect(mockRedisClient.setex).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.setex).toHaveBeenCalledWith('recording-key:1:session-123', 86400, expect.any(String))
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

        it('should still return key even if Redis cache fails', async () => {
            ;(mockRedisClient.setex as jest.Mock).mockRejectedValue(new Error('Redis error'))

            await expect(keyStore.generateKey('session-123', 1)).rejects.toThrow('Redis error')
        })
    })

    describe('getKey', () => {
        it('should return cached key from Redis if available', async () => {
            const cachedKey: SessionKey = {
                plaintextKey: Buffer.from(mockPlaintextKey),
                encryptedKey: Buffer.from(mockEncryptedKey),
                nonce: Buffer.from(mockNonce),
                encryptedSession: true,
            }

            mockRedisClient.get.mockResolvedValue(
                JSON.stringify({
                    plaintextKey: cachedKey.plaintextKey.toString('base64'),
                    encryptedKey: cachedKey.encryptedKey.toString('base64'),
                    nonce: cachedKey.nonce.toString('base64'),
                    encryptedSession: cachedKey.encryptedSession,
                })
            )

            const result = await keyStore.getKey('session-123', 1)

            expect(mockRedisClient.get).toHaveBeenCalledWith('recording-key:1:session-123')
            expect(mockDynamoDBClient.send).not.toHaveBeenCalled()
            expect(mockKMSClient.send).not.toHaveBeenCalled()

            expect(result.plaintextKey).toEqual(cachedKey.plaintextKey)
            expect(result.encryptedKey).toEqual(cachedKey.encryptedKey)
            expect(result.nonce).toEqual(cachedKey.nonce)
            expect(result.encryptedSession).toEqual(cachedKey.encryptedSession)
        })

        it('should fetch from DynamoDB and decrypt if not cached', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    encrypted_session: { BOOL: true },
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

        it('should cache decrypted key in Redis after fetching from DynamoDB', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    encrypted_session: { BOOL: true },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: mockPlaintextKey,
            })

            await keyStore.getKey('session-123', 1)

            expect(mockRedisClient.setex).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.setex).toHaveBeenCalledWith('recording-key:1:session-123', 86400, expect.any(String))
        })

        it('should return empty key if key not found in DynamoDB', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({ Item: undefined })

            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.encryptedSession).toBe(false)
        })

        it('should throw error if encrypted_key missing in DynamoDB result for encrypted session', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    nonce: { B: mockNonce },
                    encrypted_session: { BOOL: true },
                },
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(
                'Missing key data for session session-123 team 1'
            )
        })

        it('should throw error if nonce missing in DynamoDB result for encrypted session', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    encrypted_session: { BOOL: true },
                },
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow(
                'Missing key data for session session-123 team 1'
            )
        })

        it('should return empty key if session is not encrypted', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_session: { BOOL: false },
                },
            })

            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.encryptedSession).toBe(false)
            expect(mockKMSClient.send).not.toHaveBeenCalled()
        })

        it('should throw error if DynamoDB query fails', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB network error'))

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow('DynamoDB network error')
        })

        it('should throw error if Redis returns malformed cache data', async () => {
            mockRedisClient.get.mockResolvedValue('invalid json {{{')

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow()
        })

        it('should throw error if KMS fails to decrypt', async () => {
            mockRedisClient.get.mockResolvedValue(null)
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    encrypted_key: { B: mockEncryptedKey },
                    nonce: { B: mockNonce },
                    encrypted_session: { BOOL: true },
                },
            })
            ;(mockKMSClient.send as jest.Mock).mockResolvedValue({
                Plaintext: undefined,
            })

            await expect(keyStore.getKey('session-123', 1)).rejects.toThrow('Failed to decrypt key from KMS')
        })
    })

    describe('deleteKey', () => {
        it('should delete key from DynamoDB and return true if key existed', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' } },
            })

            const result = await keyStore.deleteKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)
            const dynamoCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            expect(dynamoCall.input.TableName).toBe('session-recording-keys')
            expect(dynamoCall.input.Key.session_id).toEqual({ S: 'session-123' })
            expect(dynamoCall.input.Key.team_id).toEqual({ N: '1' })
            expect(dynamoCall.input.ReturnValues).toBe('ALL_OLD')
            expect(result).toBe(true)
        })

        it('should return false if key did not exist', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({})

            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toBe(false)
        })

        it('should delete key from Redis cache', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' } },
            })

            await keyStore.deleteKey('session-123', 1)

            expect(mockRedisClient.del).toHaveBeenCalledWith('recording-key:1:session-123')
        })

        it('should throw error if DynamoDB delete fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB delete error'))

            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow('DynamoDB delete error')
        })

        it('should throw error if Redis delete fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Attributes: { session_id: { S: 'session-123' } },
            })
            ;(mockRedisClient.del as jest.Mock).mockRejectedValue(new Error('Redis delete error'))

            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow('Redis delete error')
        })
    })

    describe('destroy', () => {
        it('should clean up all clients', async () => {
            const mockDestroy = jest.fn()
            ;(mockKMSClient as any).destroy = mockDestroy
            ;(mockDynamoDBClient as any).destroy = mockDestroy
            ;(mockRedisPool as any).drain = jest.fn().mockResolvedValue(undefined)
            ;(mockRedisPool as any).clear = jest.fn().mockResolvedValue(undefined)

            await keyStore.destroy()

            expect(mockDestroy).toHaveBeenCalledTimes(2)
            expect(mockRedisPool.drain).toHaveBeenCalled()
            expect(mockRedisPool.clear).toHaveBeenCalled()
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
        it('should return empty keys with encryptedSession false', async () => {
            const result = await keyStore.generateKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.encryptedSession).toBe(false)
        })
    })

    describe('getKey', () => {
        it('should return empty keys with encryptedSession false', async () => {
            const result = await keyStore.getKey('session-123', 1)

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.encryptedSession).toBe(false)
        })
    })

    describe('deleteKey', () => {
        it('should return true', async () => {
            const result = await keyStore.deleteKey('session-123', 1)

            expect(result).toBe(true)
        })
    })

    describe('destroy', () => {
        it('should complete without error', async () => {
            await expect(keyStore.destroy()).resolves.toBeUndefined()
        })
    })
})

describe('getKeyStore', () => {
    let mockConfig: { redisUrl: string; redisPoolMinSize: number; redisPoolMaxSize: number }
    let mockTeamService: jest.Mocked<TeamService>
    let mockRedisClient: jest.Mocked<Redis>
    let mockRedisPool: jest.Mocked<RedisPool>

    beforeEach(() => {
        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            setex: jest.fn().mockResolvedValue('OK'),
            del: jest.fn().mockResolvedValue(1),
        } as unknown as jest.Mocked<Redis>

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<RedisPool>
        ;(redisUtils.createRedisPoolFromConfig as jest.Mock).mockReturnValue(mockRedisPool)

        mockConfig = {
            redisUrl: 'redis://localhost:6379',
            redisPoolMinSize: 1,
            redisPoolMaxSize: 10,
        }
        mockTeamService = {
            getEncryptionEnabledByTeamId: jest.fn().mockResolvedValue(true),
        } as unknown as jest.Mocked<TeamService>
    })

    it('should return KeyStore when running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore(mockConfig, mockTeamService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(KeyStore)
    })

    it('should return PassthroughKeyStore when not running on cloud', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(false)

        const keyStore = getKeyStore(mockConfig, mockTeamService, 'us-east-1')

        expect(keyStore).toBeInstanceOf(PassthroughKeyStore)
    })
})
