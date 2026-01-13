import { DeleteItemCommand, DynamoDBClient, GetItemCommand, PutItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'
import { LRUCache } from 'lru-cache'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { Hub, RedisPool } from '../types'
import { createRedisPoolFromConfig } from '../utils/db/redis'
import { isCloud } from '../utils/env-utils'
import { parseJSON } from '../utils/json-parse'

const KEYS_TABLE_NAME = 'session-recording-keys'
const CACHE_KEY_PREFIX = 'recording-key'
const REDIS_CACHE_TTL_SECONDS = 60 * 60 * 24 // 24 hours
const MEMORY_CACHE_MAX_SIZE = 100_000
const MEMORY_CACHE_TTL_MS = 60 * 60 * 1000 // 1 hour

export interface SessionKey {
    plaintextKey: Buffer
    encryptedKey: Buffer
    nonce: Buffer
    encryptedSession: boolean
}

export abstract class BaseKeyStore {
    abstract generateKey(sessionId: string, teamId: number): Promise<SessionKey>
    abstract getKey(sessionId: string, teamId: number): Promise<SessionKey>
    abstract deleteKey(sessionId: string, teamId: number): Promise<boolean>
    abstract destroy(): Promise<void>
}

export class PassthroughKeyStore extends BaseKeyStore {
    generateKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
            encryptedSession: false,
        })
    }

    getKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
            encryptedSession: false,
        })
    }

    deleteKey(_sessionId: string, _teamId: number): Promise<boolean> {
        return Promise.resolve(true)
    }

    destroy(): Promise<void> {
        return Promise.resolve()
    }
}

export class KeyStore extends BaseKeyStore {
    // In-memory LRU cache to avoid hitting Redis for every operation
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    private readonly memoryCache: LRUCache<string, SessionKey>

    private constructor(
        private redisPool: RedisPool,
        private dynamoDBClient: DynamoDBClient,
        private kmsClient: KMSClient,
        private retentionService: RetentionService
    ) {
        super()
        this.memoryCache = new LRUCache({
            max: MEMORY_CACHE_MAX_SIZE,
            ttl: MEMORY_CACHE_TTL_MS,
        })
    }

    static async create(
        redisPool: RedisPool,
        dynamoDBClient: DynamoDBClient,
        kmsClient: KMSClient,
        retentionService: RetentionService
    ): Promise<KeyStore> {
        await sodium.ready
        return new KeyStore(redisPool, dynamoDBClient, kmsClient, retentionService)
    }

    private cacheKey(sessionId: string, teamId: number): string {
        return `${CACHE_KEY_PREFIX}:${teamId}:${sessionId}`
    }

    private getMemoryCachedKey(sessionId: string, teamId: number): SessionKey | null {
        return this.memoryCache.get(this.cacheKey(sessionId, teamId)) ?? null
    }

    private setMemoryCachedKey(sessionId: string, teamId: number, key: SessionKey): void {
        this.memoryCache.set(this.cacheKey(sessionId, teamId), key)
    }

    private deleteMemoryCachedKey(sessionId: string, teamId: number): void {
        this.memoryCache.delete(this.cacheKey(sessionId, teamId))
    }

    private async getRedisCachedKey(sessionId: string, teamId: number): Promise<SessionKey | null> {
        const client = await this.redisPool.acquire()
        try {
            const cached = await client.get(this.cacheKey(sessionId, teamId))
            if (cached) {
                const parsed = parseJSON(cached)
                return {
                    plaintextKey: Buffer.from(parsed.plaintextKey, 'base64'),
                    encryptedKey: Buffer.from(parsed.encryptedKey, 'base64'),
                    nonce: Buffer.from(parsed.nonce, 'base64'),
                    encryptedSession: parsed.encryptedSession ?? true,
                }
            }
            return null
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setRedisCachedKey(sessionId: string, teamId: number, key: SessionKey): Promise<void> {
        const client = await this.redisPool.acquire()
        try {
            const value = JSON.stringify({
                plaintextKey: key.plaintextKey.toString('base64'),
                encryptedKey: key.encryptedKey.toString('base64'),
                nonce: key.nonce.toString('base64'),
                encryptedSession: key.encryptedSession,
            })
            await client.setex(this.cacheKey(sessionId, teamId), REDIS_CACHE_TTL_SECONDS, value)
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async deleteRedisCachedKey(sessionId: string, teamId: number): Promise<void> {
        const client = await this.redisPool.acquire()
        try {
            await client.del(this.cacheKey(sessionId, teamId))
        } finally {
            await this.redisPool.release(client)
        }
    }

    async generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        // Generate a new data encryption key using KMS
        const { Plaintext, CiphertextBlob } = await this.kmsClient.send(
            new GenerateDataKeyCommand({
                KeyId: 'alias/session-replay-master-key',
                NumberOfBytes: sodium.crypto_secretbox_KEYBYTES,
                EncryptionContext: {
                    session_id: sessionId,
                    team_id: String(teamId),
                },
            })
        )

        if (!Plaintext || !CiphertextBlob) {
            throw new Error('Failed to generate data key from KMS')
        }

        // Generate a random nonce for encryption
        const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES)

        // Calculate expiration based on session retention policy
        const sessionRetentionDays = await this.retentionService.getSessionRetentionDays(teamId, sessionId)
        const createdAt = Math.floor(Date.now() / 1000)
        const expiresAt = createdAt + sessionRetentionDays * 24 * 60 * 60

        // Store the encrypted key in DynamoDB
        await this.dynamoDBClient.send(
            new PutItemCommand({
                TableName: KEYS_TABLE_NAME,
                Item: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                    encrypted_key: { B: CiphertextBlob },
                    nonce: { B: nonce },
                    encrypted_session: { BOOL: true },
                    created_at: { N: String(createdAt) },
                    expires_at: { N: String(expiresAt) },
                },
            })
        )

        const sessionKey: SessionKey = {
            plaintextKey: Buffer.from(Plaintext),
            encryptedKey: Buffer.from(CiphertextBlob),
            nonce: Buffer.from(nonce),
            encryptedSession: true,
        }

        // Cache in memory and Redis
        this.setMemoryCachedKey(sessionId, teamId, sessionKey)
        await this.setRedisCachedKey(sessionId, teamId, sessionKey)

        return sessionKey
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        // Check memory cache first (fastest)
        const memoryCached = this.getMemoryCachedKey(sessionId, teamId)
        if (memoryCached) {
            return memoryCached
        }

        // Check Redis cache next
        const redisCached = await this.getRedisCachedKey(sessionId, teamId)
        if (redisCached) {
            // Populate memory cache for future lookups
            this.setMemoryCachedKey(sessionId, teamId, redisCached)
            return redisCached
        }

        // Fetch encrypted key and nonce from DynamoDB
        const result = await this.dynamoDBClient.send(
            new GetItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
            })
        )

        if (!result.Item) {
            throw new Error(`Key not found for session ${sessionId} team ${teamId}`)
        }

        let sessionKey: SessionKey

        if (result.Item.encrypted_session?.BOOL) {
            if (!result.Item.encrypted_key?.B || !result.Item.nonce?.B) {
                throw new Error(`Missing key data for session ${sessionId} team ${teamId}`)
            }

            const encryptedKey = Buffer.from(result.Item.encrypted_key.B)
            const nonce = Buffer.from(result.Item.nonce.B)

            // Decrypt using KMS
            const decryptResult = await this.kmsClient.send(
                new DecryptCommand({
                    CiphertextBlob: encryptedKey,
                    KeyId: 'alias/session-replay-master-key',
                    EncryptionContext: {
                        session_id: sessionId,
                        team_id: String(teamId),
                    },
                })
            )

            if (!decryptResult.Plaintext) {
                throw new Error('Failed to decrypt key from KMS')
            }

            sessionKey = {
                plaintextKey: Buffer.from(decryptResult.Plaintext),
                encryptedKey,
                nonce,
                encryptedSession: true,
            }
        } else {
            // Return empty key if session is not encrypted
            sessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                encryptedSession: false,
            }
        }

        // Cache in memory and Redis
        this.setMemoryCachedKey(sessionId, teamId, sessionKey)
        await this.setRedisCachedKey(sessionId, teamId, sessionKey)

        return sessionKey
    }

    async deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        // Delete from DynamoDB
        const result = await this.dynamoDBClient.send(
            new DeleteItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
                ReturnValues: 'ALL_OLD',
            })
        )

        // Delete from memory cache and Redis cache
        this.deleteMemoryCachedKey(sessionId, teamId)
        await this.deleteRedisCachedKey(sessionId, teamId)

        // Return true if an item was deleted
        return !!result.Attributes
    }

    async destroy(): Promise<void> {
        this.kmsClient.destroy()
        this.dynamoDBClient.destroy()
        await this.redisPool.drain()
        await this.redisPool.clear()
    }
}

export async function getKeyStore(hub: Hub, region: string): Promise<BaseKeyStore> {
    if (isCloud()) {
        const kmsClient = new KMSClient({ region })
        const dynamoDBClient = new DynamoDBClient({ region })
        const redisPool = createRedisPoolFromConfig({
            connection: { url: hub.REDIS_URL, name: 'session-recording-keystore' },
            poolMinSize: hub.REDIS_POOL_MIN_SIZE,
            poolMaxSize: hub.REDIS_POOL_MAX_SIZE,
        })

        const teamService = new TeamService(hub.postgres)
        const retentionService = new RetentionService(redisPool, teamService)

        return KeyStore.create(redisPool, dynamoDBClient, kmsClient, retentionService)
    }
    return new PassthroughKeyStore()
}
