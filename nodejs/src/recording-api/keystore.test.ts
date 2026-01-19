import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import * as envUtils from '../utils/env-utils'
import { KeyStore, PassthroughKeyStore, getKeyStore } from './keystore'
import { SessionKeyDeletedError } from './types'

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

        it('should check team encryption setting', async () => {
            await keyStore.generateKey('session-123', 42)

            expect(mockTeamService.getEncryptionEnabledByTeamId).toHaveBeenCalledWith(42)
        })

        it('should store cleartext entry when encryption is disabled', async () => {
            mockTeamService.getEncryptionEnabledByTeamId.mockResolvedValue(false)

            const result = await keyStore.generateKey('session-123', 1)

            expect(mockKMSClient.send).not.toHaveBeenCalled()
            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)

            const dynamoCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            expect(dynamoCall.input.Item.session_state).toEqual({ S: 'cleartext' })
            expect(dynamoCall.input.Item.encrypted_key).toBeUndefined()
            expect(dynamoCall.input.Item.nonce).toBeUndefined()

            expect(result.plaintextKey).toEqual(Buffer.alloc(0))
            expect(result.encryptedKey).toEqual(Buffer.alloc(0))
            expect(result.nonce).toEqual(Buffer.alloc(0))
            expect(result.sessionState).toBe('cleartext')
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
        it('should fetch from DynamoDB and decrypt', async () => {
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
            ;(mockDynamoDBClient.send as jest.Mock)
                .mockResolvedValueOnce({
                    Item: {
                        session_id: { S: 'session-123' },
                        team_id: { N: '1' },
                        session_state: { S: 'ciphertext' },
                    },
                })
                .mockResolvedValueOnce({})

            const result = await keyStore.deleteKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(2)

            const getCall = mockDynamoDBClient.send.mock.calls[0][0] as any
            expect(getCall.input.TableName).toBe('session-recording-keys')
            expect(getCall.input.Key.session_id).toEqual({ S: 'session-123' })
            expect(getCall.input.Key.team_id).toEqual({ N: '1' })

            const updateCall = mockDynamoDBClient.send.mock.calls[1][0] as any
            expect(updateCall.input.TableName).toBe('session-recording-keys')
            expect(updateCall.input.UpdateExpression).toBe(
                'SET session_state = :deleted, deleted_at = :deleted_at REMOVE encrypted_key, nonce'
            )
            expect(updateCall.input.ExpressionAttributeValues[':deleted_at']).toEqual({
                N: String(Math.floor(new Date('2024-01-15T12:00:00Z').getTime() / 1000)),
            })
            expect(result).toBe(true)
        })

        it('should return false if key did not exist', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValueOnce({ Item: undefined })

            const result = await keyStore.deleteKey('session-123', 1)

            expect(mockDynamoDBClient.send).toHaveBeenCalledTimes(1)
            expect(result).toBe(false)
        })

        it('should throw SessionKeyDeletedError if key is already deleted', async () => {
            const deletedAt = 1700000000
            ;(mockDynamoDBClient.send as jest.Mock).mockResolvedValue({
                Item: {
                    session_id: { S: 'session-123' },
                    team_id: { N: '1' },
                    session_state: { S: 'deleted' },
                    deleted_at: { N: String(deletedAt) },
                },
            })

            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow(SessionKeyDeletedError)

            try {
                await keyStore.deleteKey('session-123', 1)
            } catch (err) {
                expect((err as SessionKeyDeletedError).deletedAt).toBe(deletedAt)
            }
        })

        it('should throw error if DynamoDB get fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock).mockRejectedValue(new Error('DynamoDB get error'))

            await expect(keyStore.deleteKey('session-123', 1)).rejects.toThrow('DynamoDB get error')
        })

        it('should throw error if DynamoDB update fails', async () => {
            ;(mockDynamoDBClient.send as jest.Mock)
                .mockResolvedValueOnce({
                    Item: {
                        session_id: { S: 'session-123' },
                        session_state: { S: 'ciphertext' },
                    },
                })
                .mockRejectedValueOnce(new Error('DynamoDB update error'))

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

    it('should accept custom kmsEndpoint and dynamoDBEndpoint', () => {
        ;(envUtils.isCloud as jest.Mock).mockReturnValue(true)

        const keyStore = getKeyStore(mockTeamService, mockRetentionService, 'us-east-1', {
            kmsEndpoint: 'http://localhost:4566',
            dynamoDBEndpoint: 'http://localhost:4566',
        })

        expect(keyStore).toBeInstanceOf(KeyStore)
    })
})
