import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'

import { MlPrivacyBatchController } from './batch-controller'
import { MlKeyEncryption } from './crypto'
import { MlPrivacyDynamoDB } from './dynamodb'
import { MlSessionKeyStore } from './key-store'
import { MlKeyReader } from './reader'
import { MlKafkaEncryption } from './transport'

export interface MlPrivacyConfig {
    AI_RESEARCH_REPLAY_PRIVACY_TABLE: string
    AI_RESEARCH_REPLAY_KMS_KEY_ARN: string
    AI_RESEARCH_REPLAY_AWS_REGION: string
    AI_RESEARCH_REPLAY_KEY_CACHE_MAX: number
    AI_RESEARCH_REPLAY_KEY_CACHE_LIFETIME_MS: number
    AI_RESEARCH_REPLAY_KMS_REQUESTS_PER_SECOND: number
    SESSION_RECORDING_DYNAMODB_ENDPOINT?: string
}

export class MlPrivacyRuntime {
    public readonly encryption: MlKeyEncryption
    public readonly reader: MlKeyReader
    public readonly controller: MlPrivacyBatchController
    public readonly kafka: MlKafkaEncryption
    private readonly dynamo: DynamoDBClient
    private readonly kms: KMSClient

    constructor(config: MlPrivacyConfig) {
        if (!config.AI_RESEARCH_REPLAY_PRIVACY_TABLE || !config.AI_RESEARCH_REPLAY_KMS_KEY_ARN) {
            throw new Error('ML privacy requires a DynamoDB table and a KMS key ARN')
        }
        this.dynamo = new DynamoDBClient({
            region: config.AI_RESEARCH_REPLAY_AWS_REGION,
            endpoint: config.SESSION_RECORDING_DYNAMODB_ENDPOINT || undefined,
            maxAttempts: 3,
        })
        this.kms = new KMSClient({ region: config.AI_RESEARCH_REPLAY_AWS_REGION, maxAttempts: 3 })
        const db = new MlPrivacyDynamoDB(this.dynamo, config.AI_RESEARCH_REPLAY_PRIVACY_TABLE)
        this.encryption = new MlKeyEncryption(
            this.kms,
            config.AI_RESEARCH_REPLAY_KMS_KEY_ARN,
            config.AI_RESEARCH_REPLAY_KEY_CACHE_MAX,
            config.AI_RESEARCH_REPLAY_KEY_CACHE_LIFETIME_MS,
            8,
            config.AI_RESEARCH_REPLAY_KMS_REQUESTS_PER_SECOND
        )
        this.reader = new MlKeyReader(db, this.encryption)
        this.controller = new MlPrivacyBatchController(new MlSessionKeyStore(db, this.encryption), this.encryption)
        this.kafka = new MlKafkaEncryption(this.reader)
    }

    public start(): Promise<void> {
        return this.encryption.start()
    }

    public stop(): void {
        this.encryption.clear()
        this.dynamo.destroy()
        this.kms.destroy()
    }
}
