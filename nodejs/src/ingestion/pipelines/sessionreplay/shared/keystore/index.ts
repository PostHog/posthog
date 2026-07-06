import { DynamoDBClient } from '@aws-sdk/client-dynamodb'
import { KMSClient } from '@aws-sdk/client-kms'

import { isCloud } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'

import { CleartextKeyStore } from './cleartext-keystore'
import { DynamoDBKeyStore } from './dynamodb-keystore'

// Re-export all keystore implementations for convenience
export { CleartextKeyStore } from './cleartext-keystore'
export { DynamoDBKeyStore } from './dynamodb-keystore'
export { MemoryKeyStore } from './memory-keystore'

export interface KeyStoreConfig {
    kmsEndpoint?: string
    dynamoDBEndpoint?: string
}

export function getKeyStore(region: string, config?: KeyStoreConfig): KeyStore {
    if (isCloud()) {
        logger.info('[KeyStore] Creating DynamoDBKeyStore with AWS clients', {
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

        return new DynamoDBKeyStore(dynamoDBClient, kmsClient)
    }
    logger.info('[KeyStore] Creating CleartextKeyStore (not running on cloud)')
    return new CleartextKeyStore()
}
