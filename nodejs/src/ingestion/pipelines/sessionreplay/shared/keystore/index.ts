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
    // Per-request deadline for the AWS calls, which then abort and retry once. Unset keeps the SDK default: no deadline.
    requestTimeoutMs?: number
}

export function getKeyStore(region: string, config?: KeyStoreConfig): KeyStore {
    if (isCloud()) {
        logger.info('[KeyStore] Creating DynamoDBKeyStore with AWS clients', {
            region,
            kmsEndpoint: config?.kmsEndpoint ?? 'default',
            dynamoDBEndpoint: config?.dynamoDBEndpoint ?? 'default',
        })

        // Without throwOnRequestTimeout the SDK only logs a warning at the deadline and keeps waiting.
        const bounded = config?.requestTimeoutMs
            ? {
                  requestHandler: {
                      requestTimeout: config.requestTimeoutMs,
                      connectionTimeout: config.requestTimeoutMs,
                      throwOnRequestTimeout: true,
                  },
                  maxAttempts: 2,
              }
            : {}
        const kmsClient = new KMSClient({ region, endpoint: config?.kmsEndpoint, ...bounded })
        const dynamoDBClient = new DynamoDBClient({ region, endpoint: config?.dynamoDBEndpoint, ...bounded })

        return new DynamoDBKeyStore(dynamoDBClient, kmsClient)
    }
    logger.info('[KeyStore] Creating CleartextKeyStore (not running on cloud)')
    return new CleartextKeyStore()
}
