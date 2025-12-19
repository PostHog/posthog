import { DeleteItemCommand, DynamoDBClient, GetItemCommand, PutItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { Hub, RedisPool } from '../types'
import { createRedisPool } from '../utils/db/redis'
import { isCloud } from '../utils/env-utils'
import { parseJSON } from '../utils/json-parse'

const KEYS_TABLE_NAME = 'session-recording-keys'
const REDIS_KEY_PREFIX = 'recording-key'
const REDIS_KEY_TTL_SECONDS = 60 * 60 * 24 // 24 hours

export interface SessionKey {
    plaintextKey: Buffer
    encryptedKey: Buffer
    nonce: Buffer
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
        })
    }

    getKey(_sessionId: string, _teamId: number): Promise<SessionKey> {
        return Promise.resolve({
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            nonce: Buffer.alloc(0),
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
    private constructor(
        private redisPool: RedisPool,
        private dynamoDBClient: DynamoDBClient,
        private kmsClient: KMSClient,
        private retentionService: RetentionService
    ) {
        super()
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

    private redisKey(sessionId: string, teamId: number): string {
        return `${REDIS_KEY_PREFIX}:${teamId}:${sessionId}`
    }

    private async getCachedKey(sessionId: string, teamId: number): Promise<SessionKey | null> {
        const client = await this.redisPool.acquire()
        try {
            const cached = await client.get(this.redisKey(sessionId, teamId))
            if (cached) {
                const parsed = parseJSON(cached)
                return {
                    plaintextKey: Buffer.from(parsed.plaintextKey, 'base64'),
                    encryptedKey: Buffer.from(parsed.encryptedKey, 'base64'),
                    nonce: Buffer.from(parsed.nonce, 'base64'),
                }
            }
            return null
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async setCachedKey(sessionId: string, teamId: number, key: SessionKey): Promise<void> {
        const client = await this.redisPool.acquire()
        try {
            const value = JSON.stringify({
                plaintextKey: key.plaintextKey.toString('base64'),
                encryptedKey: key.encryptedKey.toString('base64'),
                nonce: key.nonce.toString('base64'),
            })
            await client.setex(this.redisKey(sessionId, teamId), REDIS_KEY_TTL_SECONDS, value)
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async deleteCachedKey(sessionId: string, teamId: number): Promise<void> {
        const client = await this.redisPool.acquire()
        try {
            await client.del(this.redisKey(sessionId, teamId))
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
                    created_at: { N: String(createdAt) },
                    expires_at: { N: String(expiresAt) },
                },
            })
        )

        const sessionKey: SessionKey = {
            plaintextKey: Buffer.from(Plaintext),
            encryptedKey: Buffer.from(CiphertextBlob),
            nonce: Buffer.from(nonce),
        }

        // Cache in Redis
        await this.setCachedKey(sessionId, teamId, sessionKey)

        return sessionKey
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        // Check Redis cache first
        const cached = await this.getCachedKey(sessionId, teamId)
        if (cached) {
            return cached
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

        if (!result.Item || !result.Item.encrypted_key?.B || !result.Item.nonce?.B) {
            throw new Error(`Key not found for session ${sessionId} team ${teamId}`)
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

        const sessionKey: SessionKey = {
            plaintextKey: Buffer.from(decryptResult.Plaintext),
            encryptedKey,
            nonce,
        }

        await this.setCachedKey(sessionId, teamId, sessionKey)

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

        // Delete from Redis cache
        await this.deleteCachedKey(sessionId, teamId)

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
        const redisPool = createRedisPool(hub, 'session-recording')

        const teamService = new TeamService(hub.postgres)
        const retentionService = new RetentionService(redisPool, teamService)

        return KeyStore.create(redisPool, dynamoDBClient, kmsClient, retentionService)
    }
    return new PassthroughKeyStore()
}
