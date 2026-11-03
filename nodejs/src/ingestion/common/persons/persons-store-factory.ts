import { CommonConfig } from '~/common/config'
import { PersonHogClient } from '~/common/personhog/client'
import { createIdentityClients } from '~/common/personhog/identity-clients'
import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonRepository } from '~/common/persons/repositories/person-repository'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'

import { BatchWritingPersonsStore } from './batch-writing-person-store'
import { PersonOutputs } from './person-context'
import { effectivePersonMergeEventsEnabled } from './person-merge-event'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { PersonsStore } from './persons-store'
import { RoutingPersonsStore, assertPersonsStoreModeConfig, parsePersonsStoreMode } from './routing-persons-store'

export type PersonsStoreConfig = Pick<
    IngestionConsumerConfig,
    | 'PERSON_BATCH_WRITING_DB_WRITE_MODE'
    | 'PERSON_BATCH_WRITING_USE_BATCH_UPDATES'
    | 'PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES'
    | 'PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES'
    | 'PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS'
    | 'PERSON_PROPERTIES_UPDATE_ALL'
    | 'PERSON_MERGE_LOCKED_OUTCOME_TEAM_ALLOWLIST'
    | 'PERSON_MERGE_EVENTS_ENABLED'
    | 'PERSON_MERGE_EVENTS_PARTITION_COUNT'
    | 'PERSON_MERGE_EVENTS_TEAM_ALLOWLIST'
    | 'PERSON_MERGE_NOOP_MAPPING_EMISSION_ENABLED'
    | 'PERSON_MERGE_NOOP_MAPPING_EMISSION_CACHE_SIZE'
    | 'PERSON_MERGE_NOOP_MAPPING_EMISSION_TTL_MS'
    | 'PERSONHOG_STORE_MAX_CONCURRENT_UPDATES'
    | 'PERSONHOG_SYNC_MERGE_MOVE_LIMIT'
> &
    Pick<IngestionOutputsConfig, 'INGESTION_OUTPUT_PERSON_MERGE_EVENTS_TOPIC'> &
    Pick<
        CommonConfig,
        | 'PERSONS_STORE_MODE'
        | 'PERSONHOG_ADDR'
        | 'PERSONHOG_IDENTITY_ADDR'
        | 'PERSONHOG_TLS'
        | 'PERSONHOG_TIMEOUT_MS'
        | 'PERSONHOG_IDENTITY_TIMEOUT_MS'
        | 'PERSONHOG_MERGE_TIMEOUT_MS'
        | 'PERSONHOG_READ_MAX_BYTES'
        | 'PERSONHOG_WRITE_MAX_BYTES'
        | 'PERSONHOG_INITIAL_STREAM_WINDOW_BYTES'
        | 'PERSONHOG_INITIAL_CONNECTION_WINDOW_BYTES'
    >

export interface BuiltPersonsStore {
    personsStore: PersonsStore
    /** Call after the store's shutdown: the final flush still needs the clients. */
    close: () => void
}

/** One name across the monolith and the processor split, so personhog-side metrics read the same client. */
const PERSONHOG_CLIENT_NAME = 'ingestion-persons-store'

export function buildPersonsStore(
    config: PersonsStoreConfig,
    personRepository: PersonRepository,
    outputs: PersonOutputs
): BuiltPersonsStore {
    const pgStore = new BatchWritingPersonsStore(personRepository, outputs, {
        dbWriteMode: config.PERSON_BATCH_WRITING_DB_WRITE_MODE,
        useBatchUpdates: config.PERSON_BATCH_WRITING_USE_BATCH_UPDATES,
        maxConcurrentUpdates: config.PERSON_BATCH_WRITING_MAX_CONCURRENT_UPDATES,
        maxOptimisticUpdateRetries: config.PERSON_BATCH_WRITING_MAX_OPTIMISTIC_UPDATE_RETRIES,
        optimisticUpdateRetryInterval: config.PERSON_BATCH_WRITING_OPTIMISTIC_UPDATE_RETRY_INTERVAL_MS,
        updateAllProperties: config.PERSON_PROPERTIES_UPDATE_ALL,
        mergeLockedOutcomeTeamAllowlist: config.PERSON_MERGE_LOCKED_OUTCOME_TEAM_ALLOWLIST,
        mergeEventsEnabled: effectivePersonMergeEventsEnabled(config),
        mergeEventsPartitionCount: config.PERSON_MERGE_EVENTS_PARTITION_COUNT,
        mergeEventsTeamAllowlist: config.PERSON_MERGE_EVENTS_TEAM_ALLOWLIST,
        mergeNoopMappingEmissionEnabled: config.PERSON_MERGE_NOOP_MAPPING_EMISSION_ENABLED,
        mergeNoopMappingEmissionCacheSize: config.PERSON_MERGE_NOOP_MAPPING_EMISSION_CACHE_SIZE,
        mergeNoopMappingEmissionTtlMs: config.PERSON_MERGE_NOOP_MAPPING_EMISSION_TTL_MS,
    })
    const mode = parsePersonsStoreMode(config.PERSONS_STORE_MODE)
    assertPersonsStoreModeConfig(mode, {
        routerAddr: config.PERSONHOG_ADDR,
        identityAddr: config.PERSONHOG_IDENTITY_ADDR,
    })
    if (mode === 'pg') {
        return { personsStore: pgStore, close: () => {} }
    }
    const routerClient = PersonHogClient.fromConfig({
        addr: config.PERSONHOG_ADDR,
        useTls: config.PERSONHOG_TLS,
        timeoutMs: config.PERSONHOG_TIMEOUT_MS,
        readMaxBytes: config.PERSONHOG_READ_MAX_BYTES,
        writeMaxBytes: config.PERSONHOG_WRITE_MAX_BYTES,
        clientName: PERSONHOG_CLIENT_NAME,
        initialStreamWindowBytes: config.PERSONHOG_INITIAL_STREAM_WINDOW_BYTES,
        initialConnectionWindowBytes: config.PERSONHOG_INITIAL_CONNECTION_WINDOW_BYTES,
    })
    const identityClients = createIdentityClients(
        {
            addr: config.PERSONHOG_IDENTITY_ADDR,
            useTls: config.PERSONHOG_TLS,
            timeoutMs: config.PERSONHOG_IDENTITY_TIMEOUT_MS,
            clientName: PERSONHOG_CLIENT_NAME,
            initialStreamWindowBytes: config.PERSONHOG_INITIAL_STREAM_WINDOW_BYTES,
            initialConnectionWindowBytes: config.PERSONHOG_INITIAL_CONNECTION_WINDOW_BYTES,
        },
        { mergeTimeoutMs: config.PERSONHOG_MERGE_TIMEOUT_MS }
    )
    const writeRepository = new PersonHogPersonWriteRepository(
        routerClient,
        identityClients.identity,
        PERSONHOG_CLIENT_NAME
    )
    const personhogStore = new PersonhogPersonsStore(writeRepository, {
        maxConcurrentUpdates: config.PERSONHOG_STORE_MAX_CONCURRENT_UPDATES,
        updateAllProperties: config.PERSON_PROPERTIES_UPDATE_ALL,
        syncMergeMoveLimit: config.PERSONHOG_SYNC_MERGE_MOVE_LIMIT,
        requestTimeoutMs: config.PERSONHOG_TIMEOUT_MS,
    })
    return {
        personsStore: new RoutingPersonsStore(pgStore, personhogStore, mode),
        close: () => {
            routerClient.close()
            identityClients.close()
        },
    }
}
