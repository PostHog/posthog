import { logger } from '../../utils/logger'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonRepository } from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonHogConfig } from '../config'
import { PersonHogClient } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'
import { PersonHogPersonRepository } from './personhog-person-repository'

export { PersonHogClient } from './client'
export type { PersonHogClientConfig } from './client'
export { PersonHogGroupRepository } from './personhog-group-repository'
export { PersonHogPersonRepository } from './personhog-person-repository'

export function createPersonHogClient(config: PersonHogConfig): PersonHogClient | null {
    if (!config.PERSONHOG_ENABLED || !config.PERSONHOG_ADDR) {
        return null
    }

    logger.info('🔌', `PersonHog gRPC client connecting to ${config.PERSONHOG_ADDR}`)

    return PersonHogClient.fromConfig({
        addr: config.PERSONHOG_ADDR,
        clientName: config.PLUGIN_SERVER_MODE ?? 'unknown',
        useTls: config.PERSONHOG_TLS,
        timeoutMs: config.PERSONHOG_TIMEOUT_MS,
        readMaxBytes: config.PERSONHOG_READ_MAX_BYTES,
        writeMaxBytes: config.PERSONHOG_WRITE_MAX_BYTES,
        pingIntervalMs: config.PERSONHOG_PING_INTERVAL_MS,
        pingTimeoutMs: config.PERSONHOG_PING_TIMEOUT_MS,
        pingIdleConnection: config.PERSONHOG_PING_IDLE_CONNECTION,
    })
}

export function buildGroupRepository(
    grpcClient: PersonHogClient | null,
    postgresGroupRepository: GroupRepository,
    rolloutPercentage: number,
    clientLabel: string
): GroupRepository {
    if (grpcClient && rolloutPercentage > 0) {
        logger.info('🔌', `PersonHog gRPC (groups) rollout at ${rolloutPercentage}%`)
        return new PersonHogGroupRepository(postgresGroupRepository, grpcClient, rolloutPercentage, clientLabel)
    }
    return postgresGroupRepository
}

export function buildPersonRepository(
    grpcClient: PersonHogClient | null,
    postgresPersonRepository: PersonRepository,
    rolloutPercentage: number,
    clientLabel: string
): PersonRepository {
    if (grpcClient && rolloutPercentage > 0) {
        logger.info('🔌', `PersonHog gRPC (persons) rollout at ${rolloutPercentage}%`)
        return new PersonHogPersonRepository(postgresPersonRepository, grpcClient, rolloutPercentage, clientLabel)
    }
    return postgresPersonRepository
}
