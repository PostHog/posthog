import { CommonConfig } from '../common/config'
import { logger } from '../utils/logger'
import { GroupRepository } from '../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonRepository } from '../worker/ingestion/persons/repositories/person-repository'
import { PersonHogClient } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'
import { PersonHogPersonRepository } from './personhog-person-repository'

export { PersonHogClient } from './client'
export type { PersonHogClientConfig } from './client'
export { PersonHogGroupRepository } from './personhog-group-repository'
export { PersonHogPersonRepository } from './personhog-person-repository'

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

function createGrpcClient(config: PersonHogConfig): PersonHogClient {
    return new PersonHogClient({
        addr: config.PERSONHOG_ADDR,
        useTls: config.PERSONHOG_TLS,
        timeoutMs: config.PERSONHOG_TIMEOUT_MS,
        readMaxBytes: config.PERSONHOG_READ_MAX_BYTES,
        writeMaxBytes: config.PERSONHOG_WRITE_MAX_BYTES,
        pingIntervalMs: config.PERSONHOG_PING_INTERVAL_MS,
        pingTimeoutMs: config.PERSONHOG_PING_TIMEOUT_MS,
        pingIdleConnection: config.PERSONHOG_PING_IDLE_CONNECTION,
    })
}

function isPersonHogEnabled(config: PersonHogConfig): boolean {
    return !!(config.PERSONHOG_ENABLED && config.PERSONHOG_ADDR && config.PERSONHOG_ROLLOUT_PERCENTAGE > 0)
}

export function buildGroupRepository(
    config: PersonHogConfig,
    postgresGroupRepository: GroupRepository,
    clientLabel: string
): GroupRepository {
    if (isPersonHogEnabled(config)) {
        const grpcClient = createGrpcClient(config)
        logger.info(
            '🔌',
            `PersonHog gRPC (groups) enabled at ${config.PERSONHOG_ADDR} (${config.PERSONHOG_ROLLOUT_PERCENTAGE}%)`
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

export function buildPersonRepository(
    config: PersonHogConfig,
    postgresPersonRepository: PersonRepository,
    clientLabel: string
): PersonRepository {
    if (isPersonHogEnabled(config)) {
        const grpcClient = createGrpcClient(config)
        logger.info(
            '🔌',
            `PersonHog gRPC (persons) enabled at ${config.PERSONHOG_ADDR} (${config.PERSONHOG_ROLLOUT_PERCENTAGE}%)`
        )
        return new PersonHogPersonRepository(
            postgresPersonRepository,
            grpcClient,
            config.PERSONHOG_ROLLOUT_PERCENTAGE,
            clientLabel
        )
    }
    return postgresPersonRepository
}
