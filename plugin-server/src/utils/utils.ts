import { Properties } from '@posthog/plugin-scaffold'
import { randomBytes } from 'crypto'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { Readable } from 'stream'

import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    ISOTimestamp,
    Plugin,
    PluginConfigId,
    TimestampFormat,
} from '../types'
import { logger } from './logger'
import { captureException } from './posthog'

/** Time until autoexit (due to error) gives up on graceful exit and kills the process right away. */
const GRACEFUL_EXIT_PERIOD_SECONDS = 5

export class NoRowsUpdatedError extends Error {}

export function killGracefully(): void {
    logger.error('⏲', 'Shutting plugin server down gracefully with SIGTERM...')
    process.kill(process.pid, 'SIGTERM')
    setTimeout(() => {
        logger.error('⏲', `Plugin server still running after ${GRACEFUL_EXIT_PERIOD_SECONDS} s, killing it forcefully!`)
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

export function bufferToUint32ArrayLE(buffer: Buffer): Uint32Array {
    const dataView = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength)
    const length = buffer.byteLength / 4
    const result = new Uint32Array(length)

    for (let i = 0; i < length; i++) {
        // explicitly set little-endian
        result[i] = dataView.getUint32(i * 4, true)
    }

    return result
}

export function uint32ArrayLEToBuffer(uint32Array: Uint32Array): Buffer {
    const buffer = new ArrayBuffer(uint32Array.length * 4)
    const dataView = new DataView(buffer)

    for (let i = 0; i < uint32Array.length; i++) {
        // explicitly set little-endian
        dataView.setUint32(i * 4, uint32Array[i], true)
    }
    return Buffer.from(buffer)
}

export function createRandomUint32x4(): Uint32Array {
    const randomArray = new Uint32Array(4)
    crypto.webcrypto.getRandomValues(randomArray)
    return randomArray
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

export class UUID7 extends UUID {
    constructor(bufferOrUnixTimeMs?: number | Buffer, rand?: Buffer) {
        if (bufferOrUnixTimeMs instanceof Buffer) {
            if (bufferOrUnixTimeMs.length !== 16) {
                throw new Error(`UUID7 from buffer requires 16 bytes, got ${bufferOrUnixTimeMs.length}`)
            }
            super(bufferOrUnixTimeMs)
            return
        }
        const unixTimeMs = bufferOrUnixTimeMs ?? DateTime.utc().toMillis()
        let unixTimeMsBig = BigInt(unixTimeMs)

        if (!rand) {
            rand = randomBytes(10)
        } else if (rand.length !== 10) {
            throw new Error(`UUID7 requires 10 bytes of random data, got ${rand.length}`)
        }

        // see https://www.rfc-editor.org/rfc/rfc9562#name-uuid-version-7
        // a UUIDv7 is 128 bits (16 bytes) total
        // 48 bits for unix_ts_ms,
        // 4 bits for ver = 0b111 (7)
        // 12 bits for rand_a
        // 2 bits for var = 0b10
        // 62 bits for rand_b
        // we set fully random values for rand_a and rand_b

        const array = new Uint8Array(16)
        // 48 bits for time, WILL FAIL in 10 895 CE
        // XXXXXXXX-XXXX-****-****-************
        for (let i = 5; i >= 0; i--) {
            array[i] = Number(unixTimeMsBig & 0xffn) // use last 8 binary digits to set UUID 2 hexadecimal digits
            unixTimeMsBig >>= 8n // remove these last 8 binary digits
        }
        // rand_a and rand_b
        // ********-****-*XXX-XXXX-XXXXXXXXXXXX
        array.set(rand, 6)

        // ver and var
        // ********-****-7***-X***-************
        array[6] = 0b0111_0000 | (array[6] & 0b0000_1111)
        array[8] = 0b1000_0000 | (array[8] & 0b0011_1111)

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
    const originalTimestamp = timestamp

    if (!timestamp) {
        timestamp = DateTime.utc()
    } else if (typeof timestamp === 'string') {
        timestamp = DateTime.fromISO(timestamp)
    }

    if (typeof timestamp.toUTC !== 'function') {
        logger.error('🔴', 'Timestamp is missing toUTC method after conversion', {
            originalTimestamp,
            convertedTimestamp: timestamp,
            originalType: typeof originalTimestamp,
            convertedType: typeof timestamp,
        })
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
    if (typeof timestamp.toUTC !== 'function') {
        logger.error('🔴', 'Timestamp is missing toUTC method', {
            timestamp,
            type: typeof timestamp,
        })
    }
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

export function clickHouseTimestampSecondPrecisionToISO(timestamp: ClickHouseTimestamp): ISOTimestamp {
    return DateTime.fromFormat(timestamp, DATETIME_FORMAT_CLICKHOUSE_SECOND_PRECISION, {
        zone: 'UTC',
    }).toISO() as ISOTimestamp
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
        captureException(`Had to run twice: ${errorMessage}`)
        // try one more time
        return await callback()
    }
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

export function createPostgresPool(
    connectionString: string,
    poolSize: number,
    applicationName: string,
    onError?: (error: Error) => any
): Pool {
    const pgPool = new Pool({
        connectionString,
        idleTimeoutMillis: 500,
        application_name: applicationName,
        max: poolSize,
        ssl: process.env.DYNO // Means we are on Heroku
            ? {
                  rejectUnauthorized: false,
              }
            : undefined,
    })

    const handleError =
        onError ||
        ((error) => {
            captureException(error)
            logger.error('🔴', 'PostgreSQL error encountered!\n', error)
        })

    pgPool.on('error', handleError)

    return pgPool
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

/** Get a value from a properties object by its path. This allows accessing nested properties. */
export function getPropertyValueByPath(properties: Properties, [firstKey, ...nestedKeys]: string[]): any {
    if (firstKey === undefined) {
        throw new Error('No path to property was provided')
    }
    let value = properties[firstKey]
    for (const key of nestedKeys) {
        if (value === undefined) {
            return undefined
        }
        value = value[key]
    }
    return value
}

export async function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

// Values of the $lib property that have been seen in the wild
export const KNOWN_LIB_VALUES = new Set([
    'web',
    'posthog-python',
    '',
    'js',
    'posthog-node',
    'posthog-react-native',
    'posthog-ruby',
    'posthog-ios',
    'posthog-android',
    'Segment',
    'posthog-go',
    'analytics-node',
    'RudderLabs JavaScript SDK',
    'mobile',
    'posthog-php',
    'zapier',
    'Webflow',
    'posthog-flutter',
    'com.rudderstack.android.sdk.core',
    'rudder-analytics-python',
    'rudder-ios-library',
    'rudder-analytics-php',
    'macos',
    'service_data',
    'flow',
    'PROD',
    'unknown',
    'api',
    'unbounce',
    'backend',
    'analytics-python',
    'windows',
    'cf-analytics-go',
    'server',
    'core',
    'Marketing',
    'Product',
    'com.rudderstack.android.sdk',
    'net-gibraltar',
    'posthog-java',
    'rudderanalytics-ruby',
    'GSHEETS_AIRBYTE',
    'posthog-plugin-server',
    'DotPostHog',
    'analytics-go',
    'serverless',
    'wordpress',
    'hog_function',
    'http',
    'desktop',
    'elixir',
    'DEV',
    'RudderAnalytics.NET',
    'PR',
    'railway',
    'HTTP',
    'extension',
    'cyclotron-testing',
    'RudderStack Shopify Cloud',
    'GSHEETS_MONITOR',
    'Rudder',
    'API',
    'rudder-sdk-ruby-sync',
    'curl',
])

export const getKnownLibValueOrSentinel = (lib: string): string => {
    if (lib === '') {
        return '$empty'
    }
    if (!lib) {
        return '$nil'
    }
    if (KNOWN_LIB_VALUES.has(lib)) {
        return lib
    }
    return '$other'
}

// Check if 2 maps with primitive values are equal
export const areMapsEqual = <K, V>(map1: Map<K, V>, map2: Map<K, V>): boolean => {
    if (map1.size !== map2.size) {
        return false
    }
    for (const [key, value] of map1) {
        if (!map2.has(key) || map2.get(key) !== value) {
            return false
        }
    }
    return true
}

export function promisifyCallback<TResult>(fn: (cb: (err: any, result?: TResult) => void) => void): Promise<TResult> {
    return new Promise<TResult>((resolve, reject) => {
        fn((err, result) => {
            if (err) {
                reject(err)
            } else {
                resolve(result as TResult)
            }
        })
    })
}
