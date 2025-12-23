import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'

import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { InternalPerson } from '../../types'
import { PostgresRouter } from './postgres'

export type MoveDistinctIdsResult =
    | { readonly success: true; readonly messages: TopicMessage[]; readonly distinctIdsMoved: string[] }
    | { readonly success: false; readonly error: 'TargetNotFound' }
    | { readonly success: false; readonly error: 'SourceNotFound' }

export type CreatePersonResult =
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: true
      }
    | {
          readonly success: true
          readonly person: InternalPerson
          readonly messages: TopicMessage[]
          readonly created: false
      }
    | { readonly success: false; readonly error: 'CreationConflict'; readonly distinctIds: string[] }
    | { readonly success: false; readonly error: 'PropertiesSizeViolation'; readonly distinctIds: string[] }

export interface PersonPropertiesSize {
    total_props_bytes: number
}

/** The recommended way of accessing the database. */
export class DB {
    /** Postgres connection router for database access. */
    postgres: PostgresRouter
    /** Redis used for various caches. */
    redisPool: GenericPool<Redis.Redis>
    /** Redis used to store state for cookieless ingestion. */
    redisPoolCookieless: GenericPool<Redis.Redis>

    /** Kafka producer used for syncing Postgres and ClickHouse person data. */
    kafkaProducer: KafkaProducerWrapper

    /** How many seconds to keep person info in Redis cache */
    PERSONS_AND_GROUPS_CACHE_TTL: number

    constructor(
        postgres: PostgresRouter,
        redisPool: GenericPool<Redis.Redis>,
        redisPoolCookieless: GenericPool<Redis.Redis>,
        kafkaProducer: KafkaProducerWrapper,
        personAndGroupsCacheTtl = 1
    ) {
        this.postgres = postgres
        this.redisPool = redisPool
        this.redisPoolCookieless = redisPoolCookieless
        this.kafkaProducer = kafkaProducer
        this.PERSONS_AND_GROUPS_CACHE_TTL = personAndGroupsCacheTtl
    }

    // Redis

    // Hook (EE)
}
