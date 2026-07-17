import type { CommonConfig } from '~/common/config'
import { GroupRepository } from '~/common/groups/repositories/group-repository.interface'
import { PersonRepository } from '~/common/persons/repositories/person-repository'
import { logger } from '~/common/utils/logger'

import { PersonHogClient, parseRolloutTeamIds } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'
import { PersonHogPersonRepository } from './personhog-person-repository'

export { PersonHogClient } from './client'
export type { PersonHogClientConfig } from './client'
export { PersonHogGroupRepository } from './personhog-group-repository'
export { PersonHogPersonRepository } from './personhog-person-repository'

/** PersonHog gRPC client config */
export type PersonHogConfig = Pick<
    CommonConfig,
    | 'PERSONHOG_ENABLED'
    | 'PERSONHOG_ADDR'
    | 'PERSONHOG_GROUPS_ROLLOUT_PERCENTAGE'
    | 'PERSONHOG_GROUPS_ROLLOUT_TEAM_IDS'
    | 'PERSONHOG_PERSONS_ROLLOUT_PERCENTAGE'
    | 'PERSONHOG_PERSONS_ROLLOUT_TEAM_IDS'
    | 'PERSONHOG_TLS'
    | 'PERSONHOG_TIMEOUT_MS'
    | 'PERSONHOG_READ_MAX_BYTES'
    | 'PERSONHOG_WRITE_MAX_BYTES'
    | 'PERSONHOG_PING_INTERVAL_MS'
    | 'PERSONHOG_PING_TIMEOUT_MS'
    | 'PERSONHOG_PING_IDLE_CONNECTION'
    | 'PERSONHOG_IDLE_CONNECTION_TIMEOUT_MS'
    | 'PERSONHOG_STATE_MONITOR_POLL_INTERVAL_MS'
    | 'PLUGIN_SERVER_MODE'
>

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
        idleConnectionTimeoutMs: config.PERSONHOG_IDLE_CONNECTION_TIMEOUT_MS,
        stateMonitorPollIntervalMs: config.PERSONHOG_STATE_MONITOR_POLL_INTERVAL_MS,
    })
}

export function buildGroupRepository(
    grpcClient: PersonHogClient | null,
    postgresGroupRepository: GroupRepository,
    rolloutPercentage: number,
    rolloutTeamIdsRaw: string,
    clientLabel: string
): GroupRepository {
    const rolloutTeamIds = parseRolloutTeamIds(rolloutTeamIdsRaw)
    if (grpcClient && (rolloutPercentage > 0 || rolloutTeamIds.size > 0)) {
        logger.info(
            '🔌',
            `PersonHog gRPC (groups) rollout at ${rolloutPercentage}%` +
                (rolloutTeamIds.size > 0 ? `, team IDs: [${[...rolloutTeamIds].join(', ')}]` : '')
        )
        return new PersonHogGroupRepository(
            postgresGroupRepository,
            grpcClient,
            rolloutPercentage,
            rolloutTeamIds,
            clientLabel
        )
    }
    return postgresGroupRepository
}

export function buildPersonRepository(
    grpcClient: PersonHogClient | null,
    postgresPersonRepository: PersonRepository,
    rolloutPercentage: number,
    rolloutTeamIdsRaw: string,
    clientLabel: string
): PersonRepository {
    const rolloutTeamIds = parseRolloutTeamIds(rolloutTeamIdsRaw)
    if (grpcClient && (rolloutPercentage > 0 || rolloutTeamIds.size > 0)) {
        logger.info(
            '🔌',
            `PersonHog gRPC (persons) rollout at ${rolloutPercentage}%` +
                (rolloutTeamIds.size > 0 ? `, team IDs: [${[...rolloutTeamIds].join(', ')}]` : '')
        )
        return new PersonHogPersonRepository(
            postgresPersonRepository,
            grpcClient,
            rolloutPercentage,
            rolloutTeamIds,
            clientLabel
        )
    }
    return postgresPersonRepository
}
