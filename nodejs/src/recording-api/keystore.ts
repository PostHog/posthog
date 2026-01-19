import { DynamoDBClient, GetItemCommand, PutItemCommand, UpdateItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'
import { LRUCache } from 'lru-cache'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { RedisPool } from '../types'
import { isCloud } from '../utils/env-utils'
import { parseJSON } from '../utils/json-parse'
import { logger } from '../utils/logger'

const KEYS_TABLE_NAME = 'session-recording-keys'
const CACHE_KEY_PREFIX = '@posthog/replay/recording-key'
const REDIS_CACHE_TTL_SECONDS = 60 * 60 * 24 // 24 hours
const MEMORY_CACHE_MAX_SIZE = 1_000_000
const MEMORY_CACHE_TTL_MS = 24 * 60 * 60 * 1000 // 24 hours

export type SessionState = 'ciphertext' | 'cleartext' | 'deleted'

export interface SessionKey {
    plaintextKey: Buffer
    encryptedKey: Buffer
    nonce: Buffer
    sessionState: SessionState
}

export abstract class BaseKeyStore {
    abstract start(): Promise<void>
    abstract generateKey(sessionId: string, teamId: number): Promise<SessionKey>
    abstract getKey(sessionId: string, teamId: number): Promise<SessionKey>
    abstract deleteKey(sessionId: string, teamId: number): Promise<boolean>
    abstract stop(): void
}

export class PassthroughKeyStore extends BaseKeyStore {
    start(): Promise<void> {
        return Promise.resolve()
    }

    generateKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
            sessionState: 'cleartext',
        })
    }

    getKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
            sessionState: 'cleartext',
        })
    }

    deleteKey(_sessionId: string, _teamId: number): Promise<boolean> {
        return Promise.resolve(true)
    }

    stop(): void {}
}

export class KeyStore extends BaseKeyStore {
    // In-memory LRU cache to avoid hitting DynamoDB/Redis for every operation
    // Since Kafka partitions by session ID, the same session always hits the same consumer
    private readonly memoryCache: LRUCache<string, SessionKey>
    private readonly redisCacheEnabled: boolean

    constructor(
        private dynamoDBClient: DynamoDBClient,
        private kmsClient: KMSClient,
        private retentionService: RetentionService,
        private teamService: TeamService,
        private redisPool?: RedisPool
    ) {
        super()
        this.memoryCache = new LRUCache({
            max: MEMORY_CACHE_MAX_SIZE,
            ttl: MEMORY_CACHE_TTL_MS,
        })
        this.redisCacheEnabled = !!redisPool
    }

    async start(): Promise<void> {
        await sodium.ready
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

    private async getRedisCachedKey(sessionId: string, teamId: number): Promise<SessionKey | null> {
        if (!this.redisCacheEnabled || !this.redisPool) {
            return null
        }

        const client = await this.redisPool.acquire()
        try {
            const cached = await client.get(this.cacheKey(sessionId, teamId))
            if (cached) {
                const parsed = parseJSON(cached)
                return {
                    plaintextKey: Buffer.from(parsed.plaintextKey, 'base64'),
                    encryptedKey: Buffer.from(parsed.encryptedKey, 'base64'),
                    nonce: Buffer.from(parsed.nonce, 'base64'),
                    sessionState: parsed.sessionState,
                }
            }
            return null
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setRedisCachedKey(sessionId: string, teamId: number, key: SessionKey): Promise<void> {
        if (!this.redisCacheEnabled || !this.redisPool) {
            return
        }

        const client = await this.redisPool.acquire()
        try {
            const value = JSON.stringify({
                plaintextKey: key.plaintextKey.toString('base64'),
                encryptedKey: key.encryptedKey.toString('base64'),
                nonce: key.nonce.toString('base64'),
                sessionState: key.sessionState,
            })
            await client.setex(this.cacheKey(sessionId, teamId), REDIS_CACHE_TTL_SECONDS, value)
        } finally {
            await this.redisPool.release(client)
        }
    }

    async generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        // Check if the team has encryption enabled
        const encryptionEnabled = await this.teamService.getEncryptionEnabledByTeamId(teamId)

        // Calculate expiration based on session retention policy
        const sessionRetentionDays = await this.retentionService.getSessionRetentionDays(teamId, sessionId)
        const createdAt = Math.floor(Date.now() / 1000)
        const expiresAt = createdAt + sessionRetentionDays * 24 * 60 * 60

        let sessionKey: SessionKey

        if (encryptionEnabled) {
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

            // Store the encrypted key in DynamoDB
            await this.dynamoDBClient.send(
                new PutItemCommand({
                    TableName: KEYS_TABLE_NAME,
                    Item: {
                        session_id: { S: sessionId },
                        team_id: { N: String(teamId) },
                        encrypted_key: { B: CiphertextBlob },
                        nonce: { B: nonce },
                        session_state: { S: 'ciphertext' },
                        created_at: { N: String(createdAt) },
                        expires_at: { N: String(expiresAt) },
                    },
                })
            )

            sessionKey = {
                plaintextKey: Buffer.from(Plaintext),
                encryptedKey: Buffer.from(CiphertextBlob),
                nonce: Buffer.from(nonce),
                sessionState: 'ciphertext',
            }
        } else {
            await this.dynamoDBClient.send(
                new PutItemCommand({
                    TableName: KEYS_TABLE_NAME,
                    Item: {
                        session_id: { S: sessionId },
                        team_id: { N: String(teamId) },
                        session_state: { S: 'cleartext' },
                        created_at: { N: String(createdAt) },
                        expires_at: { N: String(expiresAt) },
                    },
                })
            )

            sessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'cleartext',
            }
        }

        // Cache in memory and optionally in Redis
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

        // Check Redis cache next (if enabled)
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

        let sessionKey: SessionKey

        const sessionState = this.parseSessionState(result.Item)

        if (sessionState === 'ciphertext') {
            if (!result.Item?.encrypted_key?.B || !result.Item?.nonce?.B) {
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
                sessionState: 'ciphertext',
            }
        } else if (sessionState === 'deleted') {
            // Key was explicitly deleted - return deleted state with empty buffers
            sessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'deleted',
            }
        } else {
            // Cleartext or no record found
            sessionKey = {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'cleartext',
            }
        }

        // Cache in memory and optionally in Redis
        this.setMemoryCachedKey(sessionId, teamId, sessionKey)
        await this.setRedisCachedKey(sessionId, teamId, sessionKey)

        return sessionKey
    }

    private parseSessionState(item: Record<string, any> | undefined): SessionState {
        if (!item?.session_state?.S) {
            return 'cleartext'
        }
        return item.session_state.S as SessionState
    }

    async deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        // Mark the key as deleted in DynamoDB (don't actually delete the record)
        // This clears the encrypted_key and nonce, and sets session_state to 'deleted'
        const deletedAt = Math.floor(Date.now() / 1000)
        const result = await this.dynamoDBClient.send(
            new UpdateItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
                UpdateExpression: 'SET session_state = :deleted, deleted_at = :deleted_at REMOVE encrypted_key, nonce',
                ExpressionAttributeValues: {
                    ':deleted': { S: 'deleted' },
                    ':deleted_at': { N: String(deletedAt) },
                },
                ConditionExpression: 'attribute_exists(session_id)',
                ReturnValues: 'ALL_NEW',
            })
        )

        // Update caches with the deleted state
        const deletedKey: SessionKey = {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
            sessionState: 'deleted',
        }
        this.setMemoryCachedKey(sessionId, teamId, deletedKey)
        await this.setRedisCachedKey(sessionId, teamId, deletedKey)

        // Return true if the item was updated
        return !!result.Attributes
    }

    stop(): void {
        this.kmsClient.destroy()
        this.dynamoDBClient.destroy()
    }
}

export interface KeyStoreConfig {
    redisPool?: RedisPool
    redisCacheEnabled?: boolean
    kmsEndpoint?: string
    dynamoDBEndpoint?: string
}

export function getKeyStore(
    teamService: TeamService,
    retentionService: RetentionService,
    region: string,
    config?: KeyStoreConfig
): BaseKeyStore {
    if (isCloud()) {
        logger.info('[KeyStore] Creating KeyStore with AWS clients', {
            region,
            kmsEndpoint: config?.kmsEndpoint ?? 'default',
            dynamoDBEndpoint: config?.dynamoDBEndpoint ?? 'default',
            redisCacheEnabled: config?.redisCacheEnabled ?? false,
        })

        const kmsClient = new KMSClient({
            region,
            endpoint: config?.kmsEndpoint,
        })
        const dynamoDBClient = new DynamoDBClient({
            region,
            endpoint: config?.dynamoDBEndpoint,
        })

        // Only pass the Redis pool if caching is explicitly enabled
        const redisPool = config?.redisCacheEnabled ? config?.redisPool : undefined

        return new KeyStore(dynamoDBClient, kmsClient, retentionService, teamService, redisPool)
    }
    logger.info('[KeyStore] Creating PassthroughKeyStore (not running on cloud)')
    return new PassthroughKeyStore()
}
