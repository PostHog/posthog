import { createHash, randomBytes } from 'crypto'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'

import { ConcurrencyController } from '~/utils/concurrencyController'

/*
 * Daily-rotating salt for Hog-derived distinct_ids.
 *
 * A 128-bit random value per calendar day, stored in Redis with a TTL. Once the TTL expires the
 * salt is gone, so any hash that mixed it in becomes irreversible. This is intentionally independent
 * of cookieless ingestion — it manages its own salt under its own key — so the cookieless code stays
 * untouched and the two never share state.
 */

// Redis key namespace. Deliberately separate from cookieless (`cookieless_salt:`) — own salt, own data.
const SALT_KEY_PREFIX = 'hog_distinct_id_salt:'

// Calendar-day validity window: accept any day some timezone could currently be in (UTC−12…UTC+14),
// plus a 72h buffer. Mirrors the cookieless salt window without sharing its code.
const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14
const MAX_SUPPORTED_INGESTION_LAG_HOURS = 72

export type DailySaltResult = { success: true; salt: Buffer } | { success: false; reason: 'date_out_of_range' }

export interface DailySaltProviderConfig {
    saltTtlSeconds: number
    deleteExpiredLocalSaltsIntervalMs: number
}

export class DailySaltProvider {
    private readonly saltTtlSeconds: number
    private readonly localSaltMap: Record<string, Buffer> = {}
    private readonly mutex = new ConcurrencyController(1)
    private cleanupInterval: NodeJS.Timeout | null = null

    constructor(
        config: DailySaltProviderConfig,
        private readonly redisPool: GenericPool<Redis.Redis>
    ) {
        this.saltTtlSeconds = config.saltTtlSeconds
        // Periodically drop expired salts from the local cache; Redis TTLs handle the durable copy.
        this.cleanupInterval = setInterval(this.deleteExpiredLocalSalts, config.deleteExpiredLocalSaltsIntervalMs)
        // unref so the timer never keeps the process alive.
        this.cleanupInterval.unref()
    }

    getSaltForDay(yyyymmdd: string, timestampMs: number): Promise<DailySaltResult> {
        if (!isCalendarDateValid(yyyymmdd)) {
            return Promise.resolve({ success: false, reason: 'date_out_of_range' })
        }
        if (this.localSaltMap[yyyymmdd]) {
            return Promise.resolve({ success: true, salt: this.localSaltMap[yyyymmdd] })
        }

        // Fetch from Redis once per node process per day, behind a mutex so concurrent callers share one round-trip.
        return this.mutex.run({
            fn: async (): Promise<DailySaltResult> => {
                if (this.localSaltMap[yyyymmdd]) {
                    return { success: true, salt: this.localSaltMap[yyyymmdd] }
                }

                const key = `${SALT_KEY_PREFIX}${yyyymmdd}`
                const client = await this.redisPool.acquire()
                try {
                    const existing = await client.get(key)
                    if (existing) {
                        const salt = Buffer.from(existing, 'base64')
                        this.localSaltMap[yyyymmdd] = salt
                        return { success: true, salt }
                    }

                    // Create the day's salt, but don't overwrite a racing writer (SET NX).
                    const newSalt = randomBytes(16)
                    const setResult = await client.set(key, newSalt.toString('base64'), 'EX', this.saltTtlSeconds, 'NX')
                    if (setResult === 'OK') {
                        this.localSaltMap[yyyymmdd] = newSalt
                        return { success: true, salt: newSalt }
                    }

                    // Lost the race — read the value the winner wrote.
                    const retry = await client.get(key)
                    if (!retry) {
                        throw new Error('Failed to read Hog daily salt from redis')
                    }
                    const salt = Buffer.from(retry, 'base64')
                    this.localSaltMap[yyyymmdd] = salt
                    return { success: true, salt }
                } finally {
                    await this.redisPool.release(client)
                }
            },
            priority: timestampMs,
        })
    }

    deleteExpiredLocalSalts = (): void => {
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
    const utcDate = new Date(`${yyyymmdd}T00:00:00Z`)
    const nowUTC = new Date(Date.now())

    const startOfDayMinus12 = new Date(utcDate)
    startOfDayMinus12.setUTCHours(-MAX_NEGATIVE_TIMEZONE_HOURS)

    const endOfDayPlus14 = new Date(utcDate)
    endOfDayPlus14.setUTCHours(MAX_POSITIVE_TIMEZONE_HOURS + MAX_SUPPORTED_INGESTION_LAG_HOURS)

    return nowUTC >= startOfDayMinus12 && nowUTC < endOfDayPlus14
}
