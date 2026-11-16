import type { CommonConfig } from '~/common/config'
import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'

const VALKEY_TIMEOUT_MS = 1000

export type AttachmentQuotaValkeyConfig = Pick<
    CdpConfig,
    | 'CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_HOST'
    | 'CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PORT'
    | 'CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PASSWORD'
    | 'CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_TLS'
> &
    Pick<CommonConfig, 'REDIS_POOL_MAX_SIZE'>

/**
 * Creates a connection to the dedicated Valkey that counts the attachment upload bytes of each team for
 * each UTC day. Returns null when the host is unset.
 */
export function createAttachmentQuotaValkeyPool(config: AttachmentQuotaValkeyConfig): RedisV2 | null {
    const name = 'workflows-attachment-quota'
    if (!config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_HOST) {
        logger.info('📎', `[${name}] no attachment quota Valkey host configured`)
        return null
    }

    logger.info(
        '📎',
        `[${name}] writer=${config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_HOST}:${config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PORT} tls=${config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_TLS}`
    )

    return createRedisV2PoolFromConfig({
        connection: {
            url: config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_HOST,
            options: {
                port: config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PORT,
                password: config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PASSWORD,
                tls: config.CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_TLS ? {} : undefined,
                commandTimeout: VALKEY_TIMEOUT_MS,
                // A queued command waits for the reconnect and commandTimeout never starts for it, so a
                // dropped connection would hold the upload request until Valkey returns.
                enableOfflineQueue: false,
            },
            name,
            exitOnRepeatedErrors: false,
        },
        poolMinSize: 0,
        poolMaxSize: config.REDIS_POOL_MAX_SIZE,
        // A timed-out command stays queued on its connection; handing that connection out again would time
        // out every later upload request on it.
        discardStalledClients: true,
        acquireTimeoutMillis: VALKEY_TIMEOUT_MS,
    })
}
