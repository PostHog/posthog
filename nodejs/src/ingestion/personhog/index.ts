import { logger } from '../../utils/logger'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogConfig } from '../config'
import { PersonHogClient } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'

export { PersonHogClient } from './client'
export type { PersonHogClientConfig } from './client'
export { PersonHogGroupRepository } from './personhog-group-repository'

export function buildGroupRepository(
    config: PersonHogConfig,
    postgresGroupRepository: GroupRepository,
    clientLabel: string
): GroupRepository {
    if (config.PERSONHOG_ENABLED && config.PERSONHOG_ADDR && config.PERSONHOG_ROLLOUT_PERCENTAGE > 0) {
        const grpcClient = PersonHogClient.fromConfig({
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
