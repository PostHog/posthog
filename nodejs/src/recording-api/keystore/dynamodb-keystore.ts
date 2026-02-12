import { DynamoDBClient, GetItemCommand, PutItemCommand, UpdateItemCommand } from '@aws-sdk/client-dynamodb'
import { DecryptCommand, GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import sodium from 'libsodium-wrappers'

import { RetentionService } from '../../session-recording/retention/retention-service'
import { TeamService } from '../../session-recording/teams/team-service'
import { DeleteKeyResult, KeyStore, SessionKey } from '../types'

const KEYS_TABLE_NAME = 'session-recording-keys'

/**
 * Keystore backed by DynamoDB and KMS.
 * Used in production cloud environments for secure key management.
 */
export class DynamoDBKeyStore implements KeyStore {
    constructor(
        private dynamoDBClient: DynamoDBClient,
        private kmsClient: KMSClient,
        private retentionService: RetentionService,
        private teamService: TeamService
    ) {}

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

            await this.dynamoDBClient.send(
                new PutItemCommand({
                    TableName: KEYS_TABLE_NAME,
                    Item: {
                        session_id: { S: sessionId },
                        team_id: { N: String(teamId) },
                        encrypted_key: { B: CiphertextBlob },
                        session_state: { S: 'ciphertext' },
                        created_at: { N: String(createdAt) },
                        expires_at: { N: String(expiresAt) },
                    },
                })
            )

            sessionKey = {
                plaintextKey: Buffer.from(Plaintext),
                encryptedKey: Buffer.from(CiphertextBlob),
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

        // Verify the returned item belongs to the requested team (defense in depth)
        if (result.Item?.team_id?.N && parseInt(result.Item.team_id.N, 10) !== teamId) {
            throw new Error(`Team ID mismatch: requested ${teamId}, got ${result.Item.team_id.N}`)
        }

        const sessionState = this.parseSessionState(result.Item)

        if (sessionState === 'ciphertext') {
            if (!result.Item?.encrypted_key?.B) {
                throw new Error(`Missing key data for session ${sessionId} team ${teamId}`)
            }

            const encryptedKey = Buffer.from(result.Item.encrypted_key.B)

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
                sessionState: 'ciphertext',
            }
        } else if (sessionState === 'deleted') {
            const deletedAt = result.Item?.deleted_at?.N ? parseInt(result.Item.deleted_at.N, 10) : undefined
            return {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                sessionState: 'deleted',
                deletedAt,
            }
        }
        return {
            plaintextKey: Buffer.alloc(0),
            encryptedKey: Buffer.alloc(0),
            sessionState: 'cleartext',
        }
    }

    private parseSessionState(item: Record<string, any> | undefined): 'ciphertext' | 'cleartext' | 'deleted' {
        if (!item?.session_state?.S) {
            return 'cleartext'
        }
        return item.session_state.S as 'ciphertext' | 'cleartext' | 'deleted'
    }

    async deleteKey(sessionId: string, teamId: number): Promise<DeleteKeyResult> {
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
            return { deleted: false, reason: 'not_found' }
        }

        // Verify the returned item belongs to the requested team (defense in depth)
        if (existingItem.Item.team_id?.N && parseInt(existingItem.Item.team_id.N, 10) !== teamId) {
            throw new Error(`Team ID mismatch: requested ${teamId}, got ${existingItem.Item.team_id.N}`)
        }

        if (existingItem.Item.session_state?.S === 'deleted') {
            const deletedAt = existingItem.Item.deleted_at?.N ? parseInt(existingItem.Item.deleted_at.N, 10) : undefined
            return { deleted: false, reason: 'already_deleted', deletedAt }
        }

        const deletedAt = Math.floor(Date.now() / 1000)
        await this.dynamoDBClient.send(
            new UpdateItemCommand({
                TableName: KEYS_TABLE_NAME,
                Key: {
                    session_id: { S: sessionId },
                    team_id: { N: String(teamId) },
                },
                UpdateExpression: 'SET session_state = :deleted, deleted_at = :deleted_at REMOVE encrypted_key',
                ExpressionAttributeValues: {
                    ':deleted': { S: 'deleted' },
                    ':deleted_at': { N: String(deletedAt) },
                },
            })
        )

        return { deleted: true }
    }

    stop(): void {
        this.kmsClient.destroy()
        this.dynamoDBClient.destroy()
    }
}
