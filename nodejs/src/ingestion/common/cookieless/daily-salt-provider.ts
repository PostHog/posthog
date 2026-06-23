import { createHash, randomBytes } from 'crypto'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'
import { Counter } from 'prom-client'

import { ConcurrencyController } from '~/utils/concurrencyController'

import { RedisHelpers } from './redis-helpers'

/*
 * Daily-rotating salt: a 128-bit random value stored in Redis under `cookieless_salt:${yyyymmdd}`
 * with a TTL. Once the TTL expires the salt is deleted, so any hash that mixed it in becomes
 * impossible to reverse — this is what lets us hash PII (ip/ua) into a non-PII identifier.
 *
 * This provider is the shared leaf used by both cookieless ingestion (`CookielessManager`) and
 * the CDP source-webhook path, so they read the same salt for a given day.
 */

const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14
const MAX_SUPPORTED_INGESTION_LAG_HOURS = 72 // if changing this, you will also need to change the TTLs

export type DailySaltResult = { success: true; salt: Buffer } | { success: false; reason: 'date_out_of_range' }

export interface DailySaltProviderConfig {
    saltTtlSeconds: number
    deleteExpiredLocalSaltsIntervalMs: number
}

export class DailySaltProvider {
    public readonly redisHelpers: RedisHelpers
    private readonly saltTtlSeconds: number
    private readonly localSaltMap: Record<string, Buffer> = {}
    private readonly mutex = new ConcurrencyController(1)
    private cleanupInterval: NodeJS.Timeout | null = null

    constructor(config: DailySaltProviderConfig, redis: GenericPool<Redis.Redis>) {
        this.saltTtlSeconds = config.saltTtlSeconds
        this.redisHelpers = new RedisHelpers(redis)
        // Periodically delete expired salts from the local cache. Redis TTLs handle the durable copy;
        // dropping them locally is what keeps the PII-derived hash non-reversible once a day rolls off.
        this.cleanupInterval = setInterval(this.deleteExpiredLocalSalts, config.deleteExpiredLocalSaltsIntervalMs)
        // Call unref on the timer object, so that it doesn't prevent node from exiting.
        this.cleanupInterval.unref()
    }

    getSaltForDay(yyyymmdd: string, timestampMs: number): Promise<DailySaltResult> {
        if (!isCalendarDateValid(yyyymmdd)) {
            return Promise.resolve({ success: false, reason: 'date_out_of_range' })
        }

        // see if we have it locally
        if (this.localSaltMap[yyyymmdd]) {
            return Promise.resolve({ success: true, salt: this.localSaltMap[yyyymmdd] })
        }

        // get the salt for the day from redis, but only do this once for this node process
        return this.mutex.run({
            fn: async (): Promise<DailySaltResult> => {
                // check if we got the salt while waiting for the mutex
                if (this.localSaltMap[yyyymmdd]) {
                    return { success: true, salt: this.localSaltMap[yyyymmdd] }
                }

                // try to get it from redis instead
                const saltBase64 = await this.redisHelpers.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep',
                    { jsonSerialize: false }
                )
                if (saltBase64) {
                    cookielessCacheHitCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()
                    const salt = Buffer.from(saltBase64, 'base64')
                    this.localSaltMap[yyyymmdd] = salt
                    return { success: true, salt }
                }
                cookielessCacheMissCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()

                // try to write a new one to redis, but don't overwrite
                const newSalt = randomBytes(16)
                const setResult = await this.redisHelpers.redisSetNX(
                    `cookieless_salt:${yyyymmdd}`,
                    newSalt.toString('base64'),
                    'cookielessServerHashStep',
                    this.saltTtlSeconds,
                    { jsonSerialize: false }
                )
                if (setResult === 'OK') {
                    this.localSaltMap[yyyymmdd] = newSalt
                    return { success: true, salt: newSalt }
                }

                // if we couldn't write, it means that it exists in redis already
                const saltBase64Retry = await this.redisHelpers.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep',
                    { jsonSerialize: false }
                )
                if (!saltBase64Retry) {
                    throw new Error('Failed to get salt from redis')
                }

                const salt = Buffer.from(saltBase64Retry, 'base64')
                this.localSaltMap[yyyymmdd] = salt

                return { success: true, salt }
            },
            priority: timestampMs,
        })
    }

    deleteExpiredLocalSalts = () => {
        for (const key in this.localSaltMap) {
            if (!isCalendarDateValid(key)) {
                delete this.localSaltMap[key]
            }
        }
    }

    deleteAllLocalSalts(): void {
        for (const key in this.localSaltMap) {
            delete this.localSaltMap[key]
        }
    }

    shutdown(): void {
        if (this.cleanupInterval) {
            clearInterval(this.cleanupInterval)
            this.cleanupInterval = null
        }
        this.deleteAllLocalSalts()
    }
}

/**
 * Derive a per-team daily salt from the random daily salt. Forward-derivable from
 * (dailySalt, teamId, yyyymmdd), but not reversible — sha256 is one-way and the daily salt is
 * random and discarded after its TTL. Mixing in `teamId` isolates teams: leaking one team's
 * derived salt reveals nothing about the daily salt or any other team.
 */
export function deriveTeamDailySalt(dailySalt: Buffer, teamId: number, yyyymmdd: string): string {
    return createHash('sha256').update(dailySalt).update(`:${teamId}:${yyyymmdd}`).digest('base64')
}

export function isCalendarDateValid(yyyymmdd: string): boolean {
    // make sure that the date is not in the future, i.e. at least one timezone could plausibly be in this calendar day,
    // and not too far in the past (with some buffer for ingestion lag)
    const utcDate = new Date(`${yyyymmdd}T00:00:00Z`)

    // Current time in UTC
    const nowUTC = new Date(Date.now())

    // Define the range of the calendar day in UTC
    const startOfDayMinus12 = new Date(utcDate)
    startOfDayMinus12.setUTCHours(-MAX_NEGATIVE_TIMEZONE_HOURS) // Start at UTC−12

    const endOfDayPlus14 = new Date(utcDate)
    endOfDayPlus14.setUTCHours(MAX_POSITIVE_TIMEZONE_HOURS + MAX_SUPPORTED_INGESTION_LAG_HOURS) // End at UTC+14 (72h ingestion lag buffer)

    const isGteMinimum = nowUTC >= startOfDayMinus12
    const isLtMaximum = nowUTC < endOfDayPlus14

    // Check if the current UTC time falls within this range
    return isGteMinimum && isLtMaximum
}

const cookielessCacheHitCounter = new Counter({
    name: 'cookieless_salt_cache_hit',
    help: 'Number of local cache hits for cookieless salt',
    labelNames: ['operation', 'day'],
})

const cookielessCacheMissCounter = new Counter({
    name: 'cookieless_salt_cache_miss',
    help: 'Number of local cache misses for cookieless salt',
    labelNames: ['operation', 'day'],
})
