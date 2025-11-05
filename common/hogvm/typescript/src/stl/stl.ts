import { DateTime } from 'luxon'

import { isHogAST, isHogCallable, isHogClosure, isHogDate, isHogDateTime, isHogError, newHogError } from '../objects'
import { AsyncSTLFunction, HogDate, HogDateTime, HogInterval, STLFunction } from '../types'
import { getNestedValue, like } from '../utils'
import { md5, sha256, sha256HmacChain } from './crypto'
import {
    formatDateTime,
    fromUnixTimestamp,
    fromUnixTimestampMilli,
    now,
    toDate,
    toDateTime,
    toHogDate,
    toHogDateTime,
    toTimeZone,
    toUnixTimestamp,
    toUnixTimestampMilli,
} from './date'
import { printHogStringOutput } from './print'
import { isIPAddressInRange } from './ip'
import { inCohort, notInCohort } from './cohort'

// TODO: this file should be generated from or mergred with posthog/hogql/compiler/javascript_stl.py

function STLToString(args: any[]): string {
    if (isHogDate(args[0])) {
        const month = args[0].month
        const day = args[0].day
        return `${args[0].year}-${month < 10 ? '0' : ''}${month}-${day < 10 ? '0' : ''}${day}`
    }
    if (isHogDateTime(args[0])) {
        return DateTime.fromSeconds(args[0].dt, { zone: args[0].zone }).toISO()
    }
    return printHogStringOutput(args[0])
}

// Helper: HogInterval
// function isHogInterval(obj: any): obj is HogInterval {
//     return obj && obj.__hogInterval__ === true
// }

function toHogInterval(value: number, unit: string): HogInterval {
    return {
        __hogInterval__: true,
        value: value,
        unit: unit,
    }
}

function applyIntervalToDateTime(base: HogDate | HogDateTime, interval: HogInterval): HogDate | HogDateTime {
    let dt: DateTime
    let zone = 'UTC'
    if (isHogDateTime(base)) {
        zone = base.zone
        dt = DateTime.fromSeconds(base.dt, { zone })
    } else {
        dt = DateTime.fromObject({ year: base.year, month: base.month, day: base.day }, { zone })
    }

    const { value, unit } = interval
    // Expand certain units for uniformity
    let effectiveUnit = unit
    let effectiveValue = value
    if (unit === 'week') {
        effectiveUnit = 'day'
        effectiveValue = value * 7
    } else if (unit === 'year') {
        effectiveUnit = 'month'
        effectiveValue = value * 12
    }

    // Note: Luxon doesn't have direct month addition that can handle overflow automatically to last day of month,
    // but plus({ months: x }) will shift the date by x months and clamp automatically if needed.
    let newDt: DateTime
    switch (effectiveUnit) {
        case 'day':
            newDt = dt.plus({ days: effectiveValue })
            break
        case 'hour':
            newDt = dt.plus({ hours: effectiveValue })
            break
        case 'minute':
            newDt = dt.plus({ minutes: effectiveValue })
            break
        case 'second':
            newDt = dt.plus({ seconds: effectiveValue })
            break
        case 'month':
            newDt = dt.plus({ months: effectiveValue })
            break
        default:
            throw new Error(`Unsupported interval unit: ${unit}`)
    }

    if (isHogDateTime(base)) {
        return {
            __hogDateTime__: true,
            dt: newDt.toSeconds(),
            zone: newDt.zoneName || 'UTC',
        }
    }
    return {
        __hogDate__: true,
        year: newDt.year,
        month: newDt.month,
        day: newDt.day,
    }
}

// dateAdd(unit, amount, datetime)
function dateAddFn([unit, amount, datetime]: any[]): HogDate | HogDateTime {
    return applyIntervalToDateTime(datetime, toHogInterval(amount, unit))
}

// dateDiff(unit, start, end)
function dateDiffFn([unit, startVal, endVal]: any[]): number {
    function toDT(obj: any): DateTime {
        if (isHogDateTime(obj)) {
            return DateTime.fromSeconds(obj.dt, { zone: obj.zone })
        } else if (isHogDate(obj)) {
            return DateTime.fromObject({ year: obj.year, month: obj.month, day: obj.day }, { zone: 'UTC' })
        }
        // try parse ISO string
        return DateTime.fromISO(obj, { zone: 'UTC' })
    }

    const start = toDT(startVal)
    const end = toDT(endVal)
    const diff = end.diff(start, ['years', 'months', 'weeks', 'days', 'hours', 'minutes', 'seconds'])

    switch (unit) {
        case 'day':
            return Math.floor((end.toMillis() - start.toMillis()) / (1000 * 60 * 60 * 24))
        case 'hour':
            return Math.floor(diff.as('hours'))
        case 'minute':
            return Math.floor(diff.as('minutes'))
        case 'second':
            return Math.floor(diff.as('seconds'))
        case 'week':
            return Math.floor(diff.as('days') / 7)
        case 'month':
            // Month difference approximated by counting month differences:
            return (end.year - start.year) * 12 + (end.month - start.month)
        case 'year':
            return end.year - start.year
        default:
            throw new Error(`Unsupported unit for dateDiff: ${unit}`)
    }
}

// dateTrunc(unit, datetime)
function dateTruncFn([unit, val]: any[]): HogDateTime {
    if (!isHogDateTime(val)) {
        throw new Error('Expected a DateTime for dateTrunc')
    }
    const dt = DateTime.fromSeconds(val.dt, { zone: val.zone })
    let truncated: DateTime
    switch (unit) {
        case 'year':
            truncated = DateTime.fromObject({ year: dt.year }, { zone: dt.zoneName })
            break
        case 'month':
            truncated = DateTime.fromObject({ year: dt.year, month: dt.month }, { zone: dt.zoneName })
            break
        case 'day':
            truncated = DateTime.fromObject({ year: dt.year, month: dt.month, day: dt.day }, { zone: dt.zoneName })
            break
        case 'hour':
            truncated = DateTime.fromObject(
                { year: dt.year, month: dt.month, day: dt.day, hour: dt.hour },
                { zone: dt.zoneName }
            )
            break
        case 'minute':
            truncated = DateTime.fromObject(
                { year: dt.year, month: dt.month, day: dt.day, hour: dt.hour, minute: dt.minute },
                { zone: dt.zoneName }
            )
            break
        default:
            throw new Error(`Unsupported unit for dateTrunc: ${unit}`)
    }
    return {
        __hogDateTime__: true,
        dt: truncated.toSeconds(),
        zone: truncated.zoneName || 'UTC',
    }
}

function coalesceFn(args: any[]): any {
    for (const a of args) {
        if (a !== null && a !== undefined) {
            return a
        }
    }
    return null
}

function assumeNotNullFn([val]: any[]): any {
    if (val === null || val === undefined) {
        throw new Error('Value is null in assumeNotNull')
    }
    return val
}

function equalsFn([a, b]: any[]): boolean {
    return a === b
}

function greaterFn([a, b]: any[]): boolean {
    return a > b
}

function greaterOrEqualsFn([a, b]: any[]): boolean {
    return a >= b
}

function lessFn([a, b]: any[]): boolean {
    return a < b
}

function lessOrEqualsFn([a, b]: any[]): boolean {
    return a <= b
}

function notEqualsFn([a, b]: any[]): boolean {
    return a !== b
}

function notFn([a]: any[]): boolean {
    return !a
}

function andFn(args: any[]): boolean {
    return args.every(Boolean)
}

function orFn(args: any[]): boolean {
    return args.some(Boolean)
}

function ifFn([cond, thenVal, elseVal]: any[]): any {
    return cond ? thenVal : elseVal
}

function inFn([val, arr]: any[]): boolean {
    return Array.isArray(arr) || (arr && arr.__isHogTuple) ? arr.includes(val) : false
}

function min2Fn([a, b]: any[]): any {
    return a < b ? a : b
}

function plusFn([a, b]: any[]): any {
    return a + b
}

function minusFn([a, b]: any[]): any {
    return a - b
}

function multiIfFn(args: any[]): any {
    // multiIf(cond1, val1, cond2, val2, ..., default)
    const last = args[args.length - 1]
    const pairs = args.slice(0, -1)
    for (let i = 0; i < pairs.length; i += 2) {
        const cond = pairs[i]
        const val = pairs[i + 1]
        if (cond) {
            return val
        }
    }
    return last
}

function floorFn([a]: any[]): any {
    return Math.floor(a)
}

// extract(part, datetime)
function extractFn([part, val]: any[]): number {
    function toDT(obj: any): DateTime {
        if (isHogDateTime(obj)) {
            return DateTime.fromSeconds(obj.dt, { zone: obj.zone })
        } else if (isHogDate(obj)) {
            return DateTime.fromObject({ year: obj.year, month: obj.month, day: obj.day }, { zone: 'UTC' })
        }
        return DateTime.fromISO(obj, { zone: 'UTC' })
    }

    const dt = toDT(val)
    switch (part) {
        case 'year':
            return dt.year
        case 'month':
            return dt.month
        case 'day':
            return dt.day
        case 'hour':
            return dt.hour
        case 'minute':
            return dt.minute
        case 'second':
            return dt.second
        default:
            throw new Error(`Unknown extract part: ${part}`)
    }
}

function roundFn([a]: any[]): any {
    return Math.round(a)
}

function startsWithFn([str, prefix]: any[]): boolean {
    return typeof str === 'string' && typeof prefix === 'string' && str.startsWith(prefix)
}

function substringFn([s, start, optionalLength]: any[]): string {
    if (typeof s !== 'string') {
        return ''
    }
    const startIdx = start - 1
    const length = typeof optionalLength === 'number' ? optionalLength : s.length - startIdx
    if (startIdx < 0 || length < 0) {
        return ''
    }
    const endIdx = startIdx + length
    return startIdx < s.length ? s.slice(startIdx, endIdx) : ''
}

function addDaysFn([dateOrDt, days]: any[]): HogDate | HogDateTime {
    return applyIntervalToDateTime(dateOrDt, toHogInterval(days, 'day'))
}

function toIntervalDayFn([val]: any[]): HogInterval {
    return toHogInterval(val, 'day')
}

function toIntervalHourFn([val]: any[]): HogInterval {
    return toHogInterval(val, 'hour')
}

function toIntervalMinuteFn([val]: any[]): HogInterval {
    return toHogInterval(val, 'minute')
}

function toIntervalMonthFn([val]: any[]): HogInterval {
    return toHogInterval(val, 'month')
}

function toYearFn([val]: any[]): number {
    return extractFn(['year', val])
}

function toMonthFn([val]: any[]): number {
    return extractFn(['month', val])
}

function toStartOfDayFn([val]: any[]): HogDateTime {
    return dateTruncFn(['day', isHogDateTime(val) ? val : toDateTimeFromDate(val)])
}

function toStartOfHourFn([val]: any[]): HogDateTime {
    return dateTruncFn(['hour', isHogDateTime(val) ? val : toDateTimeFromDate(val)])
}

function toStartOfMonthFn([val]: any[]): HogDateTime {
    return dateTruncFn(['month', isHogDateTime(val) ? val : toDateTimeFromDate(val)])
}

function toStartOfWeekFn([val]: any[]): HogDateTime {
    const dt = isHogDateTime(val)
        ? DateTime.fromSeconds(val.dt, { zone: val.zone })
        : DateTime.fromObject({ year: val.year, month: val.month, day: val.day }, { zone: 'UTC' })
    const weekday = dt.weekday // Monday=1, Sunday=7
    const startOfWeek = dt.minus({ days: weekday - 1 }).startOf('day')
    return {
        __hogDateTime__: true,
        dt: startOfWeek.toSeconds(),
        zone: startOfWeek.zoneName || 'UTC',
    }
}

function toYYYYMMFn([val]: any[]): number {
    const y = toYearFn([val])
    const m = toMonthFn([val])
    return y * 100 + m
}

function todayFn(): HogDate {
    const now = DateTime.now().setZone('UTC')
    return {
        __hogDate__: true,
        year: now.year,
        month: now.month,
        day: now.day,
    }
}

function toDateTimeFromDate(date: HogDate): HogDateTime {
    const dt = DateTime.fromObject({ year: date.year, month: date.month, day: date.day }, { zone: 'UTC' })
    return {
        __hogDateTime__: true,
        dt: dt.toSeconds(),
        zone: 'UTC',
    }
}

function rangeFn(args: any[]): any[] {
    if (args.length === 1) {
        return Array.from({ length: args[0] }, (_, i) => i)
    }
    return Array.from({ length: args[1] - args[0] }, (_, i) => args[0] + i)
}

// JSON extraction
function JSONExtractArrayRawFn(args: any[]): any {
    let [obj, ...path] = args // eslint-disable-line prefer-const
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch {
        return null
    }
    const val = getNestedValue(obj, path, true)
    return Array.isArray(val) ? val : null
}

function JSONExtractFloatFn(args: any[]): number | null {
    let [obj, ...path] = args // eslint-disable-line prefer-const
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch {
        return null
    }
    const val = getNestedValue(obj, path, true)
    const f = parseFloat(val)
    return isNaN(f) ? null : f
}

function JSONExtractIntFn(args: any[]): number | null {
    let [obj, ...path] = args // eslint-disable-line prefer-const
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch {
        return null
    }
    const val = getNestedValue(obj, path, true)
    const i = parseInt(val)
    return isNaN(i) ? null : i
}

function JSONExtractStringFn(args: any[]): string | null {
    let [obj, ...path] = args // eslint-disable-line prefer-const
    try {
        if (typeof obj === 'string') {
            obj = JSON.parse(obj)
        }
    } catch {
        return null
    }
    const val = getNestedValue(obj, path, true)
    return val != null ? String(val) : null
}

export const STL: Record<string, STLFunction> = {
    concat: {
        fn: (args) => {
            return args.map((arg: any) => (arg === null ? '' : STLToString([arg]))).join('')
        },
        description: 'Concatenates multiple values into a single string',
        example: 'concat($1, $2, $3)',
        minArgs: 1,
        maxArgs: undefined,
    },
    match: {
        fn: (args, _name, options) => {
            if (!options?.external?.regex?.match) {
                throw new Error('Set options.external.regex.match for RegEx support')
            }
            return !args[0] || !args[1] ? false : options.external.regex.match(args[1], args[0])
        },
        description: 'Checks if a string matches a regex pattern',
        example: 'match($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    like: {
        fn: ([str, pattern], _name, options) => like(str, pattern, false, options?.external?.regex?.match),
        description: 'Checks if a string matches a SQL LIKE pattern',
        example: 'like($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    ilike: {
        fn: ([str, pattern], _name, options) => like(str, pattern, true, options?.external?.regex?.match),
        description: 'Case-insensitive SQL LIKE pattern matching',
        example: 'ilike($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    notLike: {
        fn: ([str, pattern], _name, options) => !like(str, pattern, false, options?.external?.regex?.match),
        description: 'Negated SQL LIKE pattern matching',
        example: 'notLike($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    notILike: {
        fn: ([str, pattern], _name, options) => !like(str, pattern, true, options?.external?.regex?.match),
        description: 'Case-insensitive negated SQL LIKE pattern matching',
        example: 'notILike($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    toString: {
        fn: STLToString,
        description: 'Converts a value to its string representation',
        example: 'toString($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toUUID: {
        fn: STLToString,
        description: 'Converts a value to a UUID string',
        example: 'toUUID($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toInt: {
        fn: (args) => {
            if (isHogDateTime(args[0])) {
                return Math.floor(args[0].dt)
            } else if (isHogDate(args[0])) {
                const day = DateTime.fromObject({ year: args[0].year, month: args[0].month, day: args[0].day })
                const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
                return Math.floor(day.diff(epoch, 'days').days)
            }
            return !isNaN(parseInt(args[0])) ? parseInt(args[0]) : null
        },
        description: 'Converts a value to an integer',
        example: 'toInt($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toFloat: {
        fn: (args) => {
            if (isHogDateTime(args[0])) {
                return args[0].dt
            } else if (isHogDate(args[0])) {
                const day = DateTime.fromObject({ year: args[0].year, month: args[0].month, day: args[0].day })
                const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
                return Math.floor(day.diff(epoch, 'days').days)
            }
            return !isNaN(parseFloat(args[0])) ? parseFloat(args[0]) : null
        },
        description: 'Converts a value to a floating point number',
        example: 'toFloat($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    // ifNull is complied into JUMP instructions. Keeping the function here for backwards compatibility
    ifNull: {
        fn: (args) => {
            return args[0] !== null ? args[0] : args[1]
        },
        description: 'Returns first non-null value',
        example: 'ifNull($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    isNull: {
        fn: (args) => {
            return args[0] === null || args[0] === undefined
        },
        description: 'Checks if a value is null or undefined',
        example: 'isNull($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    isNotNull: {
        fn: (args) => {
            return args[0] !== null && args[0] !== undefined
        },
        description: 'Checks if a value is not null and not undefined',
        example: 'isNotNull($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    length: {
        fn: (args) => {
            return args[0].length
        },
        description: 'Returns the length of a string or array',
        example: 'length($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    empty: {
        fn: (args) => {
            if (typeof args[0] === 'object') {
                if (Array.isArray(args[0])) {
                    return args[0].length === 0
                } else if (args[0] === null) {
                    return true
                } else if (args[0] instanceof Map) {
                    return args[0].size === 0
                }
                return Object.keys(args[0]).length === 0
            } else if (typeof args[0] === 'number' || typeof args[0] === 'boolean') {
                return false
            }
            return !args[0]
        },
        description: 'Checks if a value is empty (null, undefined, empty string, empty array, empty object, etc.)',
        example: 'empty($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    notEmpty: {
        fn: (args) => {
            return !STL.empty.fn(args, 'empty')
        },
        description: 'Checks if a value is not empty',
        example: 'notEmpty($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    tuple: {
        fn: (args) => {
            const tuple = args.slice()
            ;(tuple as any).__isHogTuple = true
            return tuple
        },
        description: 'Creates a tuple from multiple values',
        example: 'tuple($1, $2, $3)',
        minArgs: 0,
        maxArgs: undefined,
    },
    lower: {
        fn: (args) => {
            if (args[0] === null || args[0] === undefined) return null
            return args[0].toLowerCase()
        },
        description: 'Converts a string to lowercase',
        example: 'lower($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    upper: {
        fn: (args) => {
            return args[0].toUpperCase()
        },
        description: 'Converts a string to uppercase',
        example: 'upper($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    reverse: {
        fn: (args) => {
            return args[0].split('').reverse().join('')
        },
        description: 'Reverses a string',
        example: 'reverse($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    print: {
        fn: (args) => {
            // eslint-disable-next-line no-console
            console.log(...args.map(printHogStringOutput))
        },
        description: 'Prints values to console',
        example: 'print($1, $2)',
        minArgs: 0,
        maxArgs: undefined,
    },
    jsonParse: {
        fn: (args) => {
            // Recursively convert objects to maps
            function convert(x: any): any {
                if (Array.isArray(x)) {
                    return x.map(convert)
                } else if (typeof x === 'object' && x !== null) {
                    // DateTime and other objects will be sanitized and not converted to a map
                    if (x.__hogDateTime__) {
                        return toHogDateTime(x.dt, x.zone)
                    } else if (x.__hogDate__) {
                        return toHogDate(x.year, x.month, x.day)
                    } else if (x.__hogError__) {
                        return newHogError(x.type, x.message, x.payload)
                    }
                    // All other objects will
                    const map = new Map()
                    for (const key in x) {
                        map.set(key, convert(x[key]))
                    }
                    return map
                }
                return x
            }
            return convert(JSON.parse(args[0]))
        },
        description: 'Parses a JSON string into an object',
        example: 'jsonParse($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    jsonStringify: {
        fn: (args) => {
            // Recursively convert maps to objects
            function convert(x: any, marked?: Set<any>): any {
                if (!marked) {
                    marked = new Set()
                }
                if (typeof x === 'object' && x !== null) {
                    if (marked.has(x)) {
                        return null
                    }
                    marked.add(x)
                    try {
                        if (x instanceof Map) {
                            const obj: Record<string, any> = {}
                            x.forEach((value, key) => {
                                obj[convert(key, marked)] = convert(value, marked)
                            })
                            return obj
                        }
                        if (Array.isArray(x)) {
                            return x.map((v) => convert(v, marked))
                        }
                        if (isHogDateTime(x) || isHogDate(x) || isHogError(x) || isHogAST(x)) {
                            return x
                        }
                        if (isHogCallable(x) || isHogClosure(x)) {
                            // we don't support serializing callables
                            const callable = isHogCallable(x) ? x : x.callable
                            return `fn<${callable.name || 'lambda'}(${callable.argCount})>`
                        }
                        const obj: Record<string, any> = {}
                        for (const key in x) {
                            obj[key] = convert(x[key], marked)
                        }
                        return obj
                    } finally {
                        marked.delete(x)
                    }
                }
                return x
            }
            if (args[1] && typeof args[1] === 'number' && args[1] > 0) {
                return JSON.stringify(convert(args[0]), null, args[1])
            }
            return JSON.stringify(convert(args[0]))
        },
        description: 'Converts an object to a JSON string',
        example: 'jsonStringify($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    JSONHas: {
        fn: ([obj, ...path]) => {
            let current = obj
            for (const key of path) {
                let currentParsed = current
                if (typeof current === 'string') {
                    try {
                        currentParsed = JSON.parse(current)
                    } catch (e) {
                        return false
                    }
                }
                if (currentParsed instanceof Map) {
                    if (!currentParsed.has(key)) {
                        return false
                    }
                    current = currentParsed.get(key)
                } else if (typeof currentParsed === 'object') {
                    if (typeof key === 'number') {
                        if (Array.isArray(currentParsed)) {
                            if (key < 0) {
                                if (key < -currentParsed.length) {
                                    return false
                                }
                                current = currentParsed[currentParsed.length + key]
                            } else if (key === 0) {
                                return false
                            } else {
                                if (key > currentParsed.length) {
                                    return false
                                }
                                current = currentParsed[key - 1]
                            }
                        }
                    } else {
                        if (!(key in currentParsed)) {
                            return false
                        }
                        current = currentParsed[key]
                    }
                } else {
                    return false
                }
            }
            return true
        },
        description: 'Checks if a JSON path exists in an object',
        example: 'JSONHas($1, $2)',
        minArgs: 2,
    },
    isValidJSON: {
        fn: ([str]) => {
            try {
                JSON.parse(str)
                return true
            } catch (e) {
                return false
            }
        },
        description: 'Checks if a string is valid JSON',
        example: 'isValidJSON($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    JSONLength: {
        fn: ([obj, ...path]) => {
            try {
                if (typeof obj === 'string') {
                    obj = JSON.parse(obj)
                }
            } catch (e) {
                return 0
            }
            if (typeof obj === 'object') {
                const value = getNestedValue(obj, path, true)
                if (Array.isArray(value)) {
                    return value.length
                } else if (value instanceof Map) {
                    return value.size
                } else if (typeof value === 'object') {
                    return Object.keys(value).length
                }
            }
            return 0
        },
        description: 'Returns the length of a JSON array or object',
        example: 'JSONLength($1, $2)',
        minArgs: 2,
    },
    JSONExtractBool: {
        fn: ([obj, ...path]) => {
            try {
                if (typeof obj === 'string') {
                    obj = JSON.parse(obj)
                }
            } catch (e) {
                return false
            }
            if (path.length > 0) {
                obj = getNestedValue(obj, path, true)
            }
            if (typeof obj === 'boolean') {
                return obj
            }
            return false
        },
        description: 'Extracts a boolean value from JSON',
        example: 'JSONExtractBool($1, $2)',
        minArgs: 1,
    },
    base64Encode: {
        fn: (args) => {
            return Buffer.from(args[0]).toString('base64')
        },
        description: 'Encodes a string to base64',
        example: 'base64Encode($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    base64Decode: {
        fn: (args) => {
            return Buffer.from(args[0], 'base64').toString()
        },
        description: 'Decodes a base64 string',
        example: 'base64Decode($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    tryBase64Decode: {
        fn: (args) => {
            try {
                return Buffer.from(args[0], 'base64').toString()
            } catch (e) {
                return ''
            }
        },
        description: 'Safely decodes a base64 string, returns empty string on error',
        example: 'tryBase64Decode($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    encodeURLComponent: {
        fn: (args) => encodeURIComponent(args[0]),
        description: 'URL-encodes a string',
        example: 'encodeURLComponent($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    decodeURLComponent: {
        fn: (args) => decodeURIComponent(args[0]),
        description: 'URL-decodes a string',
        example: 'decodeURLComponent($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    replaceOne: {
        fn: (args) => {
            return args[0].replace(args[1], args[2])
        },
        description: 'Replaces first occurrence of a substring',
        example: 'replaceOne($1, $2, $3)',
        minArgs: 3,
        maxArgs: 3,
    },
    replaceAll: {
        fn: (args) => {
            return args[0].replaceAll(args[1], args[2])
        },
        description: 'Replaces all occurrences of a substring',
        example: 'replaceAll($1, $2, $3)',
        minArgs: 3,
        maxArgs: 3,
    },
    position: {
        fn: ([str, elem]) => {
            if (typeof str === 'string') {
                return str.indexOf(String(elem)) + 1
            }
            return 0
        },
        description: 'Returns position of substring in string (1-based)',
        example: 'position($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    positionCaseInsensitive: {
        fn: ([str, elem]) => {
            if (typeof str === 'string') {
                return str.toLowerCase().indexOf(String(elem).toLowerCase()) + 1
            }
            return 0
        },
        description: 'Case-insensitive substring position (1-based)',
        example: 'positionCaseInsensitive($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    trim: {
        fn: ([str, char]) => {
            if (char === null || char === undefined) {
                char = ' '
            }
            if (char.length !== 1) {
                return ''
            }
            let start = 0
            while (str[start] === char) {
                start++
            }
            let end = str.length
            while (str[end - 1] === char) {
                end--
            }
            if (start >= end) {
                return ''
            }
            return str.slice(start, end)
        },
        description: 'Removes leading and trailing characters',
        example: 'trim($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    trimLeft: {
        fn: ([str, char]) => {
            if (char === null || char === undefined) {
                char = ' '
            }
            if (char.length !== 1) {
                return ''
            }
            let start = 0
            while (str[start] === char) {
                start++
            }
            return str.slice(start)
        },
        description: 'Removes leading characters',
        example: 'trimLeft($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    trimRight: {
        fn: ([str, char]) => {
            if (char === null || char === undefined) {
                char = ' '
            }
            if (char.length !== 1) {
                return ''
            }
            let end = str.length
            while (str[end - 1] === char) {
                end--
            }
            return str.slice(0, end)
        },
        description: 'Removes trailing characters',
        example: 'trimRight($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    splitByString: {
        fn: ([separator, str, maxSplits = undefined]) => {
            if (maxSplits === undefined || maxSplits === null) {
                return str.split(separator)
            }
            return str.split(separator, maxSplits)
        },
        description: 'Splits string by separator',
        example: 'splitByString($1, $2, $3)',
        minArgs: 2,
        maxArgs: 3,
    },
    generateUUIDv4: {
        fn: () => {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                const r = (Math.random() * 16) | 0
                const v = c === 'x' ? r : (r & 0x3) | 0x8
                return v.toString(16)
            })
        },
        description: 'Generates a random UUID v4',
        example: 'generateUUIDv4()',
        minArgs: 0,
        maxArgs: 0,
    },
    sha256Hex: {
        fn: ([str], _, options) => sha256(str, 'hex', options),
        description: 'Computes SHA-256 hash of a string',
        example: 'sha256($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    sha256: {
        fn: ([str, encoding], _, options) => sha256(str, encoding, options),
        description: 'Computes SHA-256 hash of a string',
        example: 'sha256($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    md5Hex: {
        fn: ([str], _, options) => md5(str, 'hex', options),
        description: 'Computes MD5 hash of a string',
        example: 'md5($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    md5: {
        fn: ([str, encoding], _, options) => md5(str, encoding, options),
        description: 'Computes MD5 hash of a string',
        example: 'md5($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    sha256HmacChainHex: {
        fn: ([data], _, options) => sha256HmacChain(data, 'hex', options),
        description: 'Computes SHA-256 HMAC chain hash',
        example: 'sha256HmacChainHex($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    sha256HmacChain: {
        fn: ([data, encoding], _, options) => sha256HmacChain(data, encoding, options),
        description: 'Computes SHA-256 HMAC chain hash',
        example: 'sha256HmacChainHex($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    isIPAddressInRange: {
        fn: ([address, prefix]) => isIPAddressInRange(address, prefix),
        description: 'Checks if IP address is in CIDR range',
        example: 'isIPAddressInRange($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    keys: {
        fn: ([obj]) => {
            if (typeof obj === 'object') {
                if (Array.isArray(obj)) {
                    return Array.from(obj.keys())
                } else if (obj instanceof Map) {
                    return Array.from(obj.keys())
                }
                return Object.keys(obj)
            }
            return []
        },
        description: 'Returns array of object keys',
        example: 'keys($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    values: {
        fn: ([obj]) => {
            if (typeof obj === 'object') {
                if (Array.isArray(obj)) {
                    return [...obj]
                } else if (obj instanceof Map) {
                    return Array.from(obj.values())
                }
                return Object.values(obj)
            }
            return []
        },
        description: 'Returns array of object values',
        example: 'values($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    indexOf: {
        fn: ([arrOrString, elem]) => {
            if (Array.isArray(arrOrString)) {
                return arrOrString.indexOf(elem) + 1
            }
            return 0
        },
        description: 'Returns 1-based index of element in array',
        example: 'indexOf($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    arrayPushBack: {
        fn: ([arr, item]) => {
            if (!Array.isArray(arr)) {
                return [item]
            }
            return [...arr, item]
        },
        description: 'Adds element to end of array',
        example: 'arrayPushBack($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    arrayPushFront: {
        fn: ([arr, item]) => {
            if (!Array.isArray(arr)) {
                return [item]
            }
            return [item, ...arr]
        },
        description: 'Adds element to start of array',
        example: 'arrayPushFront($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    arrayPopBack: {
        fn: ([arr]) => {
            if (!Array.isArray(arr)) {
                return []
            }
            return arr.slice(0, arr.length - 1)
        },
        description: 'Removes last element from array',
        example: 'arrayPopBack($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    arrayPopFront: {
        fn: ([arr]) => {
            if (!Array.isArray(arr)) {
                return []
            }
            return arr.slice(1)
        },
        description: 'Removes first element from array',
        example: 'arrayPopFront($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    arraySort: {
        fn: ([arr]) => {
            if (!Array.isArray(arr)) {
                return []
            }
            return [...arr].sort()
        },
        description: 'Sorts array in ascending order',
        example: 'arraySort($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    arrayReverse: {
        fn: ([arr]) => {
            if (!Array.isArray(arr)) {
                return []
            }
            return [...arr].reverse()
        },
        description: 'Reverses array order',
        example: 'arrayReverse($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    arrayReverseSort: {
        fn: ([arr]) => {
            if (!Array.isArray(arr)) {
                return []
            }
            return [...arr].sort().reverse()
        },
        description: 'Sorts array in descending order',
        example: 'arrayReverseSort($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    arrayStringConcat: {
        fn: ([arr, separator = '']) => {
            if (!Array.isArray(arr)) {
                return ''
            }
            return arr.join(separator)
        },
        description: 'Joins array elements with separator',
        example: 'arrayStringConcat($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    has: {
        fn: ([arr, elem]) => {
            if (!Array.isArray(arr) || arr.length === 0) {
                return false
            }
            return arr.includes(elem)
        },
        description: 'Checks if array contains element',
        example: 'has($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    now: {
        fn: () => {
            return now()
        },
        description: 'Returns current datetime',
        example: 'now()',
        minArgs: 0,
        maxArgs: 0,
    },
    toUnixTimestamp: {
        fn: (args) => {
            return toUnixTimestamp(args[0], args[1])
        },
        description: 'Converts datetime to Unix timestamp',
        example: 'toUnixTimestamp($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    fromUnixTimestamp: {
        fn: (args) => {
            return fromUnixTimestamp(args[0])
        },
        description: 'Converts Unix timestamp to datetime',
        example: 'fromUnixTimestamp($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toUnixTimestampMilli: {
        fn: (args) => {
            return toUnixTimestampMilli(args[0], args[1])
        },
        description: 'Converts datetime to Unix timestamp in milliseconds',
        example: 'toUnixTimestampMilli($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    fromUnixTimestampMilli: {
        fn: (args) => {
            return fromUnixTimestampMilli(args[0])
        },
        description: 'Converts Unix timestamp in milliseconds to datetime',
        example: 'fromUnixTimestampMilli($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toTimeZone: {
        fn: (args) => {
            return toTimeZone(args[0], args[1])
        },
        description: 'Converts datetime to specified timezone',
        example: 'toTimeZone($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    toDate: {
        fn: (args) => {
            return toDate(args[0])
        },
        description: 'Converts value to date',
        example: 'toDate($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toDateTime: {
        fn: (args) => {
            return toDateTime(args[0], args[1])
        },
        description: 'Converts value to datetime',
        example: 'toDateTime($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    formatDateTime: {
        fn: (args) => {
            return formatDateTime(args[0], args[1], args[2])
        },
        description: 'Formats datetime with pattern',
        example: 'formatDateTime($1, $2, $3)',
        minArgs: 2,
        maxArgs: 3,
    },
    HogError: {
        fn: (args) => newHogError(args[0], args[1], args[2]),
        description: 'Creates a Hog error',
        example: 'HogError($1, $2, $3)',
        minArgs: 1,
        maxArgs: 3,
    },
    Error: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
        description: 'Creates a generic error',
        example: 'Error($1, $2)',
        minArgs: 0,
        maxArgs: 2,
    },
    RetryError: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
        description: 'Creates a retry error',
        example: 'RetryError($1, $2)',
        minArgs: 0,
        maxArgs: 2,
    },
    NotImplementedError: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
        description: 'Creates a not implemented error',
        example: 'NotImplementedError($1, $2)',
        minArgs: 0,
        maxArgs: 2,
    },
    typeof: {
        fn: (args) => {
            if (args[0] === null || args[0] === undefined) {
                return 'null'
            } else if (isHogDateTime(args[0])) {
                return 'datetime'
            } else if (isHogDate(args[0])) {
                return 'date'
            } else if (isHogError(args[0])) {
                return 'error'
            } else if (isHogCallable(args[0]) || isHogClosure(args[0])) {
                return 'function'
            } else if (isHogAST(args[0])) {
                return 'sql'
            } else if (Array.isArray(args[0])) {
                if ((args[0] as any).__isHogTuple) {
                    return 'tuple'
                }
                return 'array'
            } else if (typeof args[0] === 'object') {
                return 'object'
            } else if (typeof args[0] === 'number') {
                return Number.isInteger(args[0]) ? 'integer' : 'float'
            } else if (typeof args[0] === 'string') {
                return 'string'
            } else if (typeof args[0] === 'boolean') {
                return 'boolean'
            }
            return 'unknown'
        },
        description: 'Returns type of value as string',
        example: 'typeof($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    JSONExtractArrayRaw: {
        fn: JSONExtractArrayRawFn,
        description: 'Extracts array from JSON path',
        example: 'JSONExtractArrayRaw($1, $2)',
        minArgs: 1,
    },
    JSONExtractFloat: {
        fn: JSONExtractFloatFn,
        description: 'Extracts float from JSON path',
        example: 'JSONExtractFloat($1, $2)',
        minArgs: 1,
    },
    JSONExtractInt: {
        fn: JSONExtractIntFn,
        description: 'Extracts integer from JSON path',
        example: 'JSONExtractInt($1, $2)',
        minArgs: 1,
    },
    JSONExtractString: {
        fn: JSONExtractStringFn,
        description: 'Extracts string from JSON path',
        example: 'JSONExtractString($1, $2)',
        minArgs: 1,
    },
    addDays: {
        fn: addDaysFn,
        description: 'Adds days to date/datetime',
        example: 'addDays($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    assumeNotNull: {
        fn: assumeNotNullFn,
        description: 'Asserts value is not null',
        example: 'assumeNotNull($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    coalesce: {
        fn: coalesceFn,
        description: 'Returns first non-null value',
        example: 'coalesce($1, $2, $3)',
        minArgs: 1,
    },
    dateAdd: {
        fn: dateAddFn,
        description: 'Adds interval to date/datetime',
        example: 'dateAdd($1, $2, $3)',
        minArgs: 3,
        maxArgs: 3,
    },
    dateDiff: {
        fn: dateDiffFn,
        description: 'Returns difference between dates',
        example: 'dateDiff($1, $2, $3)',
        minArgs: 3,
        maxArgs: 3,
    },
    dateTrunc: {
        fn: dateTruncFn,
        description: 'Truncates datetime to unit',
        example: 'dateTrunc($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    equals: {
        fn: equalsFn,
        description: 'Checks if values are equal',
        example: 'equals($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    extract: {
        fn: extractFn,
        description: 'Extracts part from date/datetime',
        example: 'extract($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    floor: {
        fn: floorFn,
        description: 'Rounds number down to integer',
        example: 'floor($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    greater: {
        fn: greaterFn,
        description: 'Checks if first value is greater',
        example: 'greater($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    greaterOrEquals: {
        fn: greaterOrEqualsFn,
        description: 'Checks if first value is greater or equal',
        example: 'greaterOrEquals($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    if: {
        fn: ifFn,
        description: 'Returns value based on condition',
        example: 'if($1, $2, $3)',
        minArgs: 3,
        maxArgs: 3,
    },
    in: {
        fn: inFn,
        description: 'Checks if value is in array/tuple',
        example: 'in($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    less: {
        fn: lessFn,
        description: 'Checks if first value is less',
        example: 'less($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    lessOrEquals: {
        fn: lessOrEqualsFn,
        description: 'Checks if first value is less or equal',
        example: 'lessOrEquals($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    min2: {
        fn: min2Fn,
        description: 'Returns minimum of two values',
        example: 'min2($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    minus: {
        fn: minusFn,
        description: 'Subtracts second value from first',
        example: 'minus($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    multiIf: {
        fn: multiIfFn,
        description: 'Returns value based on multiple conditions',
        example: 'multiIf($1, $2, $3, $4, $5)',
        minArgs: 3,
    },
    not: {
        fn: notFn,
        description: 'Logical NOT operation',
        example: 'not($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    notEquals: {
        fn: notEqualsFn,
        description: 'Checks if values are not equal',
        example: 'notEquals($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    and: {
        fn: andFn,
        description: 'Logical AND operation',
        example: 'and($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    or: {
        fn: orFn,
        description: 'Logical OR operation',
        example: 'or($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    plus: {
        fn: plusFn,
        description: 'Adds two values',
        example: 'plus($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    range: {
        fn: rangeFn,
        description: 'Creates array of numbers',
        example: 'range($1, $2)',
        minArgs: 1,
        maxArgs: 2,
    },
    round: {
        fn: roundFn,
        description: 'Rounds number to nearest integer',
        example: 'round($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    startsWith: {
        fn: startsWithFn,
        description: 'Checks if string starts with prefix',
        example: 'startsWith($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    substring: {
        fn: substringFn,
        description: 'Extracts substring from string',
        example: 'substring($1, $2, $3)',
        minArgs: 2,
        maxArgs: 3,
    },
    toIntervalDay: {
        fn: toIntervalDayFn,
        description: 'Creates day interval',
        example: 'toIntervalDay($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toIntervalHour: {
        fn: toIntervalHourFn,
        description: 'Creates hour interval',
        example: 'toIntervalHour($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toIntervalMinute: {
        fn: toIntervalMinuteFn,
        description: 'Creates minute interval',
        example: 'toIntervalMinute($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toIntervalMonth: {
        fn: toIntervalMonthFn,
        description: 'Creates month interval',
        example: 'toIntervalMonth($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toMonth: {
        fn: toMonthFn,
        description: 'Extracts month from date/datetime',
        example: 'toMonth($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toStartOfDay: {
        fn: toStartOfDayFn,
        description: 'Truncates datetime to start of day',
        example: 'toStartOfDay($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toStartOfHour: {
        fn: toStartOfHourFn,
        description: 'Truncates datetime to start of hour',
        example: 'toStartOfHour($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toStartOfMonth: {
        fn: toStartOfMonthFn,
        description: 'Truncates datetime to start of month',
        example: 'toStartOfMonth($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toStartOfWeek: {
        fn: toStartOfWeekFn,
        description: 'Truncates datetime to start of week',
        example: 'toStartOfWeek($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toYYYYMM: {
        fn: toYYYYMMFn,
        description: 'Converts date to YYYYMM format',
        example: 'toYYYYMM($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    toYear: {
        fn: toYearFn,
        description: 'Extracts year from date/datetime',
        example: 'toYear($1)',
        minArgs: 1,
        maxArgs: 1,
    },
    today: {
        fn: todayFn,
        description: 'Returns current date',
        example: 'today()',
        minArgs: 0,
        maxArgs: 0,
    },
    inCohort: {
        fn: inCohort,
        description: 'Checks if cohort ID is in list of person cohorts',
        example: 'inCohort($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
    notInCohort: {
        fn: notInCohort,
        description: 'Checks if cohort ID is NOT in list of person cohorts',
        example: 'notInCohort($1, $2)',
        minArgs: 2,
        maxArgs: 2,
    },
}

export const ASYNC_STL: Record<string, AsyncSTLFunction> = {
    sleep: {
        fn: async (args) => {
            await new Promise((resolve) => setTimeout(resolve, args[0] * 1000))
        },
        minArgs: 1,
        maxArgs: 1,
    },
}
