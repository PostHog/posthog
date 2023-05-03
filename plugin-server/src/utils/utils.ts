import Piscina from '@posthog/piscina'
import * as Sentry from '@sentry/node'
import { randomBytes } from 'crypto'
import Redis, { RedisOptions } from 'ioredis'
import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { Readable } from 'stream'

import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    ISOTimestamp,
    Plugin,
    PluginConfigId,
    PluginsServerConfig,
    TimestampFormat,
} from '../types'
import { Hub } from './../types'
import { status } from './status'

/** Time until autoexit (due to error) gives up on graceful exit and kills the process right away. */
const GRACEFUL_EXIT_PERIOD_SECONDS = 5
/** Number of Redis error events until the server is killed gracefully. */
const REDIS_ERROR_COUNTER_LIMIT = 10

export class NoRowsUpdatedError extends Error {}

export function killGracefully(): void {
    status.error('⏲', 'Shutting plugin server down gracefully with SIGTERM...')
    process.kill(process.pid, 'SIGTERM')
    setTimeout(() => {
        status.error('⏲', `Plugin server still running after ${GRACEFUL_EXIT_PERIOD_SECONDS} s, killing it forcefully!`)
        process.exit(1)
    }, GRACEFUL_EXIT_PERIOD_SECONDS * 1000)
}

/**
 * @param binary Buffer
 * returns readableInstanceStream Readable
 */
export function bufferToStream(binary: Buffer): Readable {
    const readableInstanceStream = new Readable({
        read() {
            this.push(binary)
            this.push(null)
        },
    })

    return readableInstanceStream
}

export function cloneObject<T>(obj: T): T {
    if (obj !== Object(obj)) {
        return obj
    }
    if (Array.isArray(obj)) {
        return (obj as any[]).map(cloneObject) as unknown as T
    }
    const clone: Record<string, any> = {}
    for (const i in obj) {
        clone[i] = cloneObject(obj[i])
    }
    return clone as T
}

/** LUT of byte value to hexadecimal representation. For UUID stringification. */
const byteToHex: string[] = []
for (let i = 0; i < 256; i++) {
    byteToHex.push((i + 0x100).toString(16).substr(1))
}

export class UUID {
    /**
     * Check whether str
     *
     * This does not care about RFC4122, since neither does UUIDT above.
     * https://stackoverflow.com/questions/7905929/how-to-test-valid-uuid-guid
     */

    static validateString(candidate: any, throwOnInvalid = true): boolean {
        const isValid = Boolean(
            candidate &&
                typeof candidate === 'string' &&
                candidate.match(/^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$/i)
        )
        if (!isValid && throwOnInvalid) {
            throw new Error(
                'String does not match format XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX (where each X is a hexadecimal character)!'
            )
        }
        return isValid
    }

    array: Uint8Array

    constructor(candidate: string | Uint8Array | Buffer) {
        if (candidate instanceof Uint8Array) {
            if (candidate.byteLength !== 16) {
                throw new Error(`UUID must be built from exactly 16 bytes, but you provided ${candidate.byteLength}!`)
            }
            this.array = new Uint8Array(candidate)
        } else {
            candidate = candidate.trim()
            UUID.validateString(candidate)
            this.array = new Uint8Array(16)
            const characters = Array.from(candidate).filter((character) => character !== '-')
            for (let i = 0; i < characters.length; i += 2) {
                this.array[i / 2] = parseInt(characters[i] + characters[i + 1], 16)
            }
        }
    }

    /** Convert to 128-bit BigInt. */
    valueOf(): bigint {
        let value = 0n
        for (const byte of this.array) {
            value <<= 8n
            value += BigInt(byte)
        }
        return value
    }

    /**
     * Convert to string format of the form:
     * XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
     */
    toString(): string {
        // Adapted from https://github.com/uuidjs/uuid/blob/master/src/stringify.js
        // Note: Be careful editing this code! It's been tuned for performance and works in ways you may not expect.
        // See https://github.com/uuidjs/uuid/pull/434
        const arr = this.array
        return (
            byteToHex[arr[0]] +
            byteToHex[arr[1]] +
            byteToHex[arr[2]] +
            byteToHex[arr[3]] +
            '-' +
            byteToHex[arr[4]] +
            byteToHex[arr[5]] +
            '-' +
            byteToHex[arr[6]] +
            byteToHex[arr[7]] +
            '-' +
            byteToHex[arr[8]] +
            byteToHex[arr[9]] +
            '-' +
            byteToHex[arr[10]] +
            byteToHex[arr[11]] +
            byteToHex[arr[12]] +
            byteToHex[arr[13]] +
            byteToHex[arr[14]] +
            byteToHex[arr[15]]
        ).toLowerCase()
    }
}

/**
 * UUID (mostly) sortable by generation time.
 *
 * This doesn't adhere to any official UUID version spec, but it is superior as a primary key:
 * to incremented integers (as they can reveal sensitive business information about usage volumes and patterns),
 * to UUID v4 (as the complete randomness of v4 makes its indexing performance suboptimal),
 * and to UUID v1 (as despite being time-based it can't be used practically for sorting by generation time).
 *
 * Order can be messed up if system Unix time is changed or if more than 65 536 IDs are generated per millisecond
 * (that's over 5 trillion events per day), but it should be largely safe to assume that these are time-sortable.
 *
 * Anatomy:
 * - 6 bytes - Unix time milliseconds unsigned integer
 * - 2 bytes - autoincremented series unsigned integer (per millisecond, rolls over to 0 after reaching 65 535 UUIDs in one ms)
 * - 8 bytes - securely random gibberish
 *
 * Loosely based on [Segment's KSUID](https://github.com/segmentio/ksuid) and
 * on [Twitter's snowflake ID](https://blog.twitter.com/engineering/en_us/a/2010/announcing-snowflake.html).
 * Ported from the PostHog Django app.
 */
export class UUIDT extends UUID {
    static currentSeriesPerMs: Map<number, number> = new Map()

    /** Get per-millisecond series integer in range [0-65536). */
    static getSeries(unixTimeMs: number): number {
        const series = UUIDT.currentSeriesPerMs.get(unixTimeMs) ?? 0
        if (UUIDT.currentSeriesPerMs.size > 10_000) {
            // Clear class dict periodically
            UUIDT.currentSeriesPerMs.clear()
        }
        UUIDT.currentSeriesPerMs.set(unixTimeMs, (series + 1) % 65_536)
        return series
    }

    constructor(unixTimeMs?: number) {
        if (!unixTimeMs) {
            unixTimeMs = DateTime.utc().toMillis()
        }
        let unixTimeMsBig = BigInt(unixTimeMs)
        let series = UUIDT.getSeries(unixTimeMs)
        // 64 bits (8 bytes) total
        const array = new Uint8Array(16)
        // 48 bits for time, WILL FAIL in 10 895 CE
        // XXXXXXXX-XXXX-****-****-************
        for (let i = 5; i >= 0; i--) {
            array[i] = Number(unixTimeMsBig & 0xffn) // use last 8 binary digits to set UUID 2 hexadecimal digits
            unixTimeMsBig >>= 8n // remove these last 8 binary digits
        }
        // 16 bits for series
        // ********-****-XXXX-****-************
        for (let i = 7; i >= 6; i--) {
            array[i] = series & 0xff // use last 8 binary digits to set UUID 2 hexadecimal digits
            series >>>= 8 // remove these last 8 binary digits
        }
        // 64 bits for random gibberish
        // ********-****-****-XXXX-XXXXXXXXXXXX
        array.set(randomBytes(8), 8)
        super(array)
    }
}

/* Format timestamps.
Allowed timestamp formats support ISO and ClickHouse formats according to
`timestampFormat`. This distinction is relevant because ClickHouse does NOT
 necessarily accept all possible ISO timestamps. */
export function castTimestampOrNow(
    timestamp?: DateTime | string | null,
    timestampFormat?: TimestampFormat.ISO
): ISOTimestamp
export function castTimestampOrNow(
    timestamp: DateTime | string | null,
    timestampFormat: TimestampFormat.ClickHouse
): ClickHouseTimestamp
export function castTimestampOrNow(
    timestamp: DateTime | string | null,
    timestampFormat: TimestampFormat.ClickHouseSecondPrecision
): ClickHouseTimestampSecondPrecision
export function castTimestampOrNow(
    timestamp?: DateTime | string | null,
    timestampFormat: TimestampFormat = TimestampFormat.ISO
): ISOTimestamp | ClickHouseTimestamp | ClickHouseTimestampSecondPrecision {
    if (!timestamp) {
        timestamp = DateTime.utc()
    } else if (typeof timestamp === 'string') {
        timestamp = DateTime.fromISO(timestamp)
    }

    return castTimestampToClickhouseFormat(timestamp, timestampFormat)
}

const DATETIME_FORMAT_CLICKHOUSE_SECOND_PRECISION = 'yyyy-MM-dd HH:mm:ss'
const DATETIME_FORMAT_CLICKHOUSE = 'yyyy-MM-dd HH:mm:ss.u'

export function castTimestampToClickhouseFormat(timestamp: DateTime, timestampFormat: TimestampFormat.ISO): ISOTimestamp
export function castTimestampToClickhouseFormat(
    timestamp: DateTime,
    timestampFormat: TimestampFormat.ClickHouse
): ClickHouseTimestamp
export function castTimestampToClickhouseFormat(
    timestamp: DateTime,
    timestampFormat: TimestampFormat.ClickHouseSecondPrecision
): ClickHouseTimestampSecondPrecision
export function castTimestampToClickhouseFormat(
    timestamp: DateTime,
    timestampFormat: TimestampFormat
): ISOTimestamp | ClickHouseTimestamp | ClickHouseTimestampSecondPrecision
export function castTimestampToClickhouseFormat(
    timestamp: DateTime,
    timestampFormat: TimestampFormat = TimestampFormat.ISO
): ISOTimestamp | ClickHouseTimestamp | ClickHouseTimestampSecondPrecision {
    timestamp = timestamp.toUTC()
    switch (timestampFormat) {
        case TimestampFormat.ClickHouseSecondPrecision:
            return timestamp.toFormat(DATETIME_FORMAT_CLICKHOUSE_SECOND_PRECISION) as ClickHouseTimestampSecondPrecision
        case TimestampFormat.ClickHouse:
            return timestamp.toFormat(DATETIME_FORMAT_CLICKHOUSE) as ClickHouseTimestamp
        case TimestampFormat.ISO:
            return timestamp.toUTC().toISO() as ISOTimestamp
        default:
            throw new Error(`Unrecognized timestamp format ${timestampFormat}!`)
    }
}

// Used only when parsing clickhouse timestamps
export function clickHouseTimestampToDateTime(timestamp: ClickHouseTimestamp): DateTime {
    return DateTime.fromFormat(timestamp, DATETIME_FORMAT_CLICKHOUSE, { zone: 'UTC' })
}

export function clickHouseTimestampToISO(timestamp: ClickHouseTimestamp): ISOTimestamp {
    return clickHouseTimestampToDateTime(timestamp).toISO() as ISOTimestamp
}

export function delay(ms: number): Promise<void> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

/** Remove all quotes from the provided identifier to prevent SQL injection. */
export function sanitizeSqlIdentifier(unquotedIdentifier: string): string {
    return unquotedIdentifier.replace(/[^\w\d_]+/g, '')
}

/** Escape single quotes and slashes */
export function escapeClickHouseString(string: string): string {
    // In string literals, you need to escape at least `'` and `\`.
    // https://clickhouse.tech/docs/en/sql-reference/syntax/
    return string.replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

export function groupIntoBatches<T>(array: T[], batchSize: number): T[][] {
    const batches = []
    for (let i = 0; i < array.length; i += batchSize) {
        batches.push(array.slice(i, i + batchSize))
    }
    return batches
}

/** Standardize JS code used internally to form without extraneous indentation. Template literal function. */
export function code(strings: TemplateStringsArray): string {
    const stringsConcat = strings.join('…')
    const indentation = stringsConcat.match(/^\n([ ]*)/)?.[1].length ?? 0
    const dedentedCode = stringsConcat.replace(new RegExp(`^[ ]{${indentation}}`, 'gm'), '')
    return dedentedCode.trim()
}

export async function tryTwice<T>(callback: () => Promise<T>, errorMessage: string, timeoutMs = 5000): Promise<T> {
    const timeout = new Promise((_, reject) => setTimeout(reject, timeoutMs))
    try {
        const response = await Promise.race([timeout, callback()])
        return response as T
    } catch (error) {
        Sentry.captureMessage(`Had to run twice: ${errorMessage}`)
        // try one more time
        return await callback()
    }
}

export async function createRedis(serverConfig: PluginsServerConfig): Promise<Redis.Redis> {
    const credentials: Partial<RedisOptions> | undefined = serverConfig.POSTHOG_REDIS_HOST
        ? {
              password: serverConfig.POSTHOG_REDIS_PASSWORD,
              port: serverConfig.POSTHOG_REDIS_PORT,
          }
        : undefined

    const redis = new Redis(credentials ? serverConfig.POSTHOG_REDIS_HOST : serverConfig.REDIS_URL, {
        ...credentials,
        maxRetriesPerRequest: -1,
    })
    let errorCounter = 0
    redis
        .on('error', (error) => {
            errorCounter++
            Sentry.captureException(error)
            if (errorCounter > REDIS_ERROR_COUNTER_LIMIT) {
                status.error('😡', 'Redis error encountered! Enough of this, I quit!\n', error)
                killGracefully()
            } else {
                status.error('🔴', 'Redis error encountered! Trying to reconnect...\n', error)
            }
        })
        .on('ready', () => {
            if (process.env.NODE_ENV !== 'test') {
                status.info('✅', 'Connected to Redis!')
            }
        })
    await redis.info()
    return redis
}

export function pluginDigest(plugin: Plugin | Plugin['id'], teamId?: number): string {
    if (typeof plugin === 'number') {
        return `plugin ID ${plugin} (unknown)`
    }
    const extras = []
    if (teamId) {
        extras.push(`team ID ${teamId}`)
    }
    extras.push(`organization ID ${plugin.organization_id}`)
    if (plugin.is_global) {
        extras.push('global')
    }
    return `plugin ${plugin.name} ID ${plugin.id} (${extras.join(' - ')})`
}

export function createPostgresPool(connectionString: string, onError?: (error: Error) => any): Pool {
    const pgPool = new Pool({
        connectionString,
        idleTimeoutMillis: 500,
        max: 10,
        ssl: process.env.DYNO // Means we are on Heroku
            ? {
                  rejectUnauthorized: false,
              }
            : undefined,
    })

    const handleError =
        onError ||
        ((error) => {
            Sentry.captureException(error)
            status.error('🔴', 'PostgreSQL error encountered!\n', error)
        })

    pgPool.on('error', handleError)

    return pgPool
}

export function getPiscinaStats(piscina: Piscina): Record<string, number> {
    return {
        utilization: (piscina.utilization || 0) * 100,
        threads: piscina.threads.length,
        queue_size: piscina.queueSize,
        'waitTime.average': piscina.waitTime.average,
        'waitTime.mean': piscina.waitTime.mean,
        'waitTime.stddev': piscina.waitTime.stddev,
        'waitTime.min': piscina.waitTime.min,
        'waitTime.p99_99': piscina.waitTime.p99_99,
        'waitTime.p99': piscina.waitTime.p99,
        'waitTime.p95': piscina.waitTime.p95,
        'waitTime.p90': piscina.waitTime.p90,
        'waitTime.p75': piscina.waitTime.p75,
        'waitTime.p50': piscina.waitTime.p50,
        'runTime.average': piscina.runTime.average,
        'runTime.mean': piscina.runTime.mean,
        'runTime.stddev': piscina.runTime.stddev,
        'runTime.min': piscina.runTime.min,
        'runTime.p99_99': piscina.runTime.p99_99,
        'runTime.p99': piscina.runTime.p99,
        'runTime.p95': piscina.runTime.p95,
        'runTime.p90': piscina.runTime.p90,
        'runTime.p75': piscina.runTime.p75,
        'runTime.p50': piscina.runTime.p50,
    }
}

export function pluginConfigIdFromStack(
    stack: string,
    pluginConfigSecretLookup: Map<string, PluginConfigId>
): PluginConfigId | void {
    // This matches `pluginConfigIdentifier` from worker/vm/vm.ts
    // For example: "at __asyncGuard__PluginConfig_39_3af03d... (vm.js:11..."
    const regexp = /at __[a-zA-Z0-9]+__PluginConfig_([0-9]+)_([0-9a-f]+) \(vm\.js\:/
    const [, id, hash] =
        stack
            .split('\n')
            .map((l) => l.match(regexp))
            .filter((a) => a)
            .pop() || [] // using pop() to get the lowest matching stack entry, avoiding higher user-defined functions

    if (id && hash) {
        const secretId = pluginConfigSecretLookup.get(hash)
        if (secretId === parseInt(id)) {
            return secretId
        }
    }
}

export function logOrThrowJobQueueError(server: PluginsServerConfig, error: Error, message: string): void {
    Sentry.captureException(error)
    if (server.CRASH_IF_NO_PERSISTENT_JOB_QUEUE) {
        status.error('🔴', message)
        throw error
    } else {
        status.info('🟡', message)
    }
}

export function groupBy<T extends Record<string, any>, K extends keyof T>(
    objects: T[],
    key: K,
    flat?: false
): Record<T[K], T[]>
export function groupBy<T extends Record<string, any>, K extends keyof T>(
    objects: T[],
    key: K,
    flat: true
): Record<T[K], T>
export function groupBy<T extends Record<string, any>, K extends keyof T>(
    objects: T[],
    key: K,
    flat = false
): Record<T[K], T[] | T> {
    return flat
        ? objects.reduce((grouping, currentItem) => {
              if (currentItem[key] in grouping) {
                  throw new Error(
                      `Key "${String(key)}" has more than one matching value, which is not allowed in flat groupBy!`
                  )
              }
              grouping[currentItem[key]] = currentItem
              return grouping
          }, {} as Record<T[K], T>)
        : objects.reduce((grouping, currentItem) => {
              ;(grouping[currentItem[key]] = grouping[currentItem[key]] || []).push(currentItem)
              return grouping
          }, {} as Record<T[K], T[]>)
}

export function clamp(value: number, min: number, max: number): number {
    return value > max ? max : value < min ? min : value
}

export function stringClamp(value: string, def: number, min: number, max: number): number {
    const nanToNull = (nr: number): null | number => (isNaN(nr) ? null : nr)
    return clamp(nanToNull(parseInt(value)) ?? def, min, max)
}

export function stringify(value: any): string {
    switch (typeof value) {
        case 'string':
            return value
        case 'undefined':
            return 'undefined'
        default:
            return JSON.stringify(value)
    }
}

export class IllegalOperationError extends Error {
    name = 'IllegalOperationError'

    constructor(operation: string) {
        super(operation)
    }
}

export function getByAge<K, V>(cache: Map<K, [V, number]>, key: K, maxAgeMs = 30_000): V | undefined {
    if (cache.has(key)) {
        const [value, age] = cache.get(key)!
        if (Date.now() - age <= maxAgeMs) {
            return value
        }
    }
    return undefined
}

// Equivalent of Python's string.ascii_letters
export function getAsciiLetters(): string {
    const LOWERCASE_START_POINT = 97 // ASCII 'a'
    const UPPERCASE_START_POINT = 65 // ASCII 'A'

    const lowercaseLetters = Array.from({ length: 26 }).map((_, i) => String.fromCharCode(LOWERCASE_START_POINT + i))
    const uppercaseLetters = Array.from({ length: 26 }).map((_, i) => String.fromCharCode(UPPERCASE_START_POINT + i))

    return `${lowercaseLetters.join('')}${uppercaseLetters.join('')}`
}

// Equivalent of Python's string.digits
export function getAllDigits(): string {
    return Array.from({ length: 10 })
        .map((_, i) => i)
        .join('')
}

export function generateRandomToken(nBytes: number): string {
    return intToBase(Number.parseInt(randomBytes(nBytes).toString('hex'), 16), 62)
}

export function intToBase(num: number, base: number): string {
    if (base > 62) {
        throw new IllegalOperationError('Cannot convert integer to base above 62')
    }
    const alphabet = getAllDigits() + getAsciiLetters()
    if (num < 0) {
        return '-' + intToBase(-num, base)
    }
    let value = ''
    while (num != 0) {
        const oldNum = num
        num = Math.floor(oldNum / alphabet.length)
        const index = oldNum % alphabet.length
        value = alphabet[index] + value
    }

    return value || '0'
}

// For errors we want to explicitly throw
// concerning race conditions across threads
export class RaceConditionError extends Error {
    name = 'RaceConditionError'
}

export interface StalenessCheckResult {
    isServerStale: boolean
    timeSinceLastActivity: number | null
    lastActivity?: string | null
    lastActivityType?: string
    instanceId?: string
}

export function stalenessCheck(hub: Hub | undefined, stalenessSeconds: number): StalenessCheckResult {
    let isServerStale = false

    const timeSinceLastActivity = hub?.lastActivity ? new Date().valueOf() - hub.lastActivity : null
    if (timeSinceLastActivity && timeSinceLastActivity > stalenessSeconds * 1000) {
        isServerStale = true
    }

    return {
        isServerStale,
        timeSinceLastActivity,
        instanceId: hub?.instanceId.toString(),
        lastActivity: hub?.lastActivity ? new Date(hub.lastActivity).toISOString() : null,
        lastActivityType: hub?.lastActivityType,
    }
}
