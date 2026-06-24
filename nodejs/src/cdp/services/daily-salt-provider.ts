import { createHash, randomBytes } from 'crypto'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'

import { logger } from '~/utils/logger'

/*
 * Daily-rotating salt for Hog-derived distinct_ids.
 *
 * A 128-bit random value per calendar day, stored in Redis with a TTL. Once the TTL expires the
 * salt is gone, so any hash that mixed it in becomes irreversible — even to us. That irreversibility
 * is the whole point: it only holds because the salt is genuinely random and discarded, not derived
 * from any retained secret. Independent of cookieless ingestion (own key, own salt).
 */

// Redis key namespace. Deliberately separate from cookieless (`cookieless_salt:`) — own salt, own data.
const SALT_KEY_PREFIX = 'hog_distinct_id_salt:'
const SALT_BYTES = 16

// Calendar-day validity window: accept any day some timezone could currently be in (UTC−12…UTC+14),
// plus a 72h buffer. Callers only ever ask for "today", so this is just a cheap sanity guard.
const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14
const MAX_SUPPORTED_INGESTION_LAG_HOURS = 72

export type DailySaltResult = { success: true; salt: Buffer } | { success: false; reason: 'date_out_of_range' }

export class DailySaltProvider {
    // Only ever holds today's salt (callers always ask for "today"), so it stays at ~1 entry — no cleanup needed.
    private readonly localSaltMap: Record<string, Buffer> = {}

    constructor(
        private readonly saltTtlSeconds: number,
        private readonly redisPool: GenericPool<Redis.Redis>
    ) {}

    async getSaltForDay(yyyymmdd: string): Promise<DailySaltResult> {
        if (!isCalendarDateValid(yyyymmdd)) {
            return { success: false, reason: 'date_out_of_range' }
        }
        const cached = this.localSaltMap[yyyymmdd]
        if (cached) {
            return { success: true, salt: cached }
        }

        const key = `${SALT_KEY_PREFIX}${yyyymmdd}`
        const client = await this.redisPool.acquire()
        try {
            let salt = await this.readSalt(client, key)
            if (!salt) {
                // Create the day's salt, but don't overwrite a racing writer (SET NX).
                const newSalt = randomBytes(SALT_BYTES)
                const setResult = await client.set(key, newSalt.toString('base64'), 'EX', this.saltTtlSeconds, 'NX')
                salt = setResult === 'OK' ? newSalt : await this.readSalt(client, key)
            }
            if (!salt) {
                throw new Error('Failed to read Hog daily salt from redis')
            }
            this.localSaltMap[yyyymmdd] = salt
            return { success: true, salt }
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async readSalt(client: Redis.Redis, key: string): Promise<Buffer | null> {
        const b64 = await client.get(key)
        if (!b64) {
            return null
        }
        const salt = Buffer.from(b64, 'base64')
        if (salt.length !== SALT_BYTES) {
            // Corrupt/poisoned value — ignore it rather than derive ids from a malformed salt.
            logger.warn('Hog daily salt has unexpected length; ignoring', { length: salt.length })
            return null
        }
        return salt
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
