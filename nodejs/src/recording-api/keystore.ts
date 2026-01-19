import { DynamoDBClient, GetItemCommand, PutItemCommand, UpdateItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { isCloud } from '../utils/env-utils'
import { logger } from '../utils/logger'
import { BaseKeyStore, SessionKey, SessionKeyDeletedError } from './types'

const KEYS_TABLE_NAME = 'session-recording-keys'

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
    constructor(
        private dynamoDBClient: DynamoDBClient,
        private kmsClient: KMSClient,
        private retentionService: RetentionService,
        private teamService: TeamService
    ) {
        super()
    }

    async start(): Promise<void> {
        await sodium.ready
    }

    async generateKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const encryptionEnabled = await this.teamService.getEncryptionEnabledByTeamId(teamId)

        const sessionRetentionDays = await this.retentionService.getSessionRetentionDays(teamId, sessionId)
        const createdAt = Math.floor(Date.now() / 1000)
        const expiresAt = createdAt + sessionRetentionDays * 24 * 60 * 60

        let sessionKey: SessionKey

        if (encryptionEnabled) {
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

            const nonce = sodium.randombytes_buf(sodium.crypto_secretbox_NONCEBYTES)

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

        return sessionKey
    }

    async getKey(sessionId: string, teamId: number): Promise<SessionKey> {
        const result = await this.dynamoDBClient.send(
            new GetItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
            })
        )

        const sessionState = this.parseSessionState(result.Item)

        if (sessionState === 'ciphertext') {
            if (!result.Item?.encrypted_key?.B || !result.Item?.nonce?.B) {
                throw new Error(`Missing key data for session ${sessionId} team ${teamId}`)
            }

            const encryptedKey = Buffer.from(result.Item.encrypted_key.B)
            const nonce = Buffer.from(result.Item.nonce.B)

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

            return {
                plaintextKey: Buffer.from(decryptResult.Plaintext),
                encryptedKey,
                nonce,
                sessionState: 'ciphertext',
            }
        } else if (sessionState === 'deleted') {
            const deletedAt = result.Item?.deleted_at?.N ? parseInt(result.Item.deleted_at.N, 10) : undefined
            return {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt,
            }
        } else {
            return {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                nonce: Buffer.alloc(0),
                sessionState: 'cleartext',
            }
        }
    }

    private parseSessionState(item: Record<string, any> | undefined): 'ciphertext' | 'cleartext' | 'deleted' {
        if (!item?.session_state?.S) {
            return 'cleartext'
        }
        return item.session_state.S as 'ciphertext' | 'cleartext' | 'deleted'
    }

    async deleteKey(sessionId: string, teamId: number): Promise<boolean> {
        const existingItem = await this.dynamoDBClient.send(
            new GetItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
            })
        )

        if (!existingItem.Item) {
            return false
        }

        if (existingItem.Item.session_state?.S === 'deleted') {
            const deletedAt = existingItem.Item.deleted_at?.N ? parseInt(existingItem.Item.deleted_at.N, 10) : 0
            throw new SessionKeyDeletedError(sessionId, teamId, deletedAt)
        }

        const deletedAt = Math.floor(Date.now() / 1000)
        await this.dynamoDBClient.send(
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
            })
        )

        return true
    }

    stop(): void {
        this.kmsClient.destroy()
        this.dynamoDBClient.destroy()
    }
}

export interface KeyStoreConfig {
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
        })

        const kmsClient = new KMSClient({
            region,
            endpoint: config?.kmsEndpoint,
        })
        const dynamoDBClient = new DynamoDBClient({
            region,
            endpoint: config?.dynamoDBEndpoint,
        })

        return new KeyStore(dynamoDBClient, kmsClient, retentionService, teamService)
    }
    logger.info('[KeyStore] Creating PassthroughKeyStore (not running on cloud)')
    return new PassthroughKeyStore()
}
