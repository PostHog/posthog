import { CommonConfig } from '../common/config'
import { logger } from '../utils/logger'
import { GroupRepository } from '../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogClient } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'

export { PersonHogClient } from './client'
export type { PersonHogClientConfig } from './client'
export { PersonHogGroupRepository } from './personhog-group-repository'

type PersonHogConfig = Pick<
    CommonConfig,
    | 'PERSONHOG_ENABLED'
    | 'PERSONHOG_ADDR'
    | 'PERSONHOG_ROLLOUT_PERCENTAGE'
    | 'PERSONHOG_TLS'
    | 'PERSONHOG_TIMEOUT_MS'
    | 'PERSONHOG_READ_MAX_BYTES'
    | 'PERSONHOG_WRITE_MAX_BYTES'
    | 'PERSONHOG_PING_INTERVAL_MS'
    | 'PERSONHOG_PING_TIMEOUT_MS'
    | 'PERSONHOG_PING_IDLE_CONNECTION'
>

export function buildGroupRepository(
    config: PersonHogConfig,
    postgresGroupRepository: GroupRepository,
    clientLabel: string
): GroupRepository {
    if (config.PERSONHOG_ENABLED && config.PERSONHOG_ADDR && config.PERSONHOG_ROLLOUT_PERCENTAGE > 0) {
        const grpcClient = new PersonHogClient({
            addr: config.PERSONHOG_ADDR,
            useTls: config.PERSONHOG_TLS,
            timeoutMs: config.PERSONHOG_TIMEOUT_MS,
            readMaxBytes: config.PERSONHOG_READ_MAX_BYTES,
            writeMaxBytes: config.PERSONHOG_WRITE_MAX_BYTES,
            pingIntervalMs: config.PERSONHOG_PING_INTERVAL_MS,
            pingTimeoutMs: config.PERSONHOG_PING_TIMEOUT_MS,
            pingIdleConnection: config.PERSONHOG_PING_IDLE_CONNECTION,
        })
        logger.info(
            '🔌',
            `PersonHog gRPC enabled at ${config.PERSONHOG_ADDR} (${config.PERSONHOG_ROLLOUT_PERCENTAGE}%)`
        )
        return new PersonHogGroupRepository(
            postgresGroupRepository,
            grpcClient,
            config.PERSONHOG_ROLLOUT_PERCENTAGE,
            clientLabel
        )
    }
    return postgresGroupRepository
}
