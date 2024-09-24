import { DateTime } from 'luxon'

import { isHogCallable, isHogClosure, isHogDate, isHogDateTime, isHogError, newHogError } from '../objects'
import { AsyncSTLFunction, STLFunction } from '../types'
import { getNestedValue, like } from '../utils'
import { md5Hex, sha256Hex, sha256HmacChainHex } from './crypto'
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

export const STL: Record<string, STLFunction> = {
    concat: {
        fn: (args) => {
            return args.map((arg: any) => (arg === null ? '' : STLToString([arg]))).join('')
        },
        minArgs: 1,
        maxArgs: undefined,
    },
    match: {
        fn: (args, _name, options) => {
            if (!options?.external?.regex?.match) {
                throw new Error('Set options.external.regex.match for RegEx support')
            }
            return options.external.regex.match(args[1], args[0])
        },
        minArgs: 2,
        maxArgs: 2,
    },
    like: { fn: ([str, pattern], _name, options) => like(str, pattern, false, options?.external?.regex?.match), minArgs: 2, maxArgs: 2 },
    ilike: { fn: ([str, pattern], _name, options) => like(str, pattern, true, options?.external?.regex?.match), minArgs: 2, maxArgs: 2 },
    notLike: { fn: ([str, pattern], _name, options) => !like(str, pattern, false, options?.external?.regex?.match), minArgs: 2, maxArgs: 2 },
    notILike: { fn: ([str, pattern], _name, options) => !like(str, pattern, true, options?.external?.regex?.match), minArgs: 2, maxArgs: 2 },
    toString: { fn: STLToString, minArgs: 1, maxArgs: 1 },
    toUUID: {
        fn: (args) => {
            return String(args[0])
        },
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
        minArgs: 1,
        maxArgs: 1,
    },
    // ifNull is complied into JUMP instructions. Keeping the function here for backwards compatibility
    ifNull: {
        fn: (args) => {
            return args[0] !== null ? args[0] : args[1]
        },
        minArgs: 2,
        maxArgs: 2,
    },
    length: {
        fn: (args) => {
            return args[0].length
        },
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
        minArgs: 1,
        maxArgs: 1,
    },
    notEmpty: {
        fn: (args) => {
            return !STL.empty.fn(args, 'empty')
        },
        minArgs: 1,
        maxArgs: 1,
    },
    tuple: {
        fn: (args) => {
            const tuple = args.slice()
            ;(tuple as any).__isHogTuple = true
            return tuple
        },
        minArgs: 0,
        maxArgs: undefined,
    },
    lower: {
        fn: (args) => {
            return args[0].toLowerCase()
        },
        minArgs: 1,
        maxArgs: 1,
    },
    upper: {
        fn: (args) => {
            return args[0].toUpperCase()
        },
        minArgs: 1,
        maxArgs: 1,
    },
    reverse: {
        fn: (args) => {
            return args[0].split('').reverse().join('')
        },
        minArgs: 1,
        maxArgs: 1,
    },
    print: {
        fn: (args) => {
            // eslint-disable-next-line no-console
            console.log(...args.map(printHogStringOutput))
        },
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
                        if (isHogDateTime(x) || isHogDate(x) || isHogError(x)) {
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
        minArgs: 2,
    },
    base64Encode: {
        fn: (args) => {
            return Buffer.from(args[0]).toString('base64')
        },
        minArgs: 1,
        maxArgs: 1,
    },
    base64Decode: {
        fn: (args) => {
            return Buffer.from(args[0], 'base64').toString()
        },
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
        minArgs: 1,
        maxArgs: 1,
    },
    encodeURLComponent: {
        fn: (args) => encodeURIComponent(args[0]),
        minArgs: 1,
        maxArgs: 1,
    },
    decodeURLComponent: {
        fn: (args) => decodeURIComponent(args[0]),
        minArgs: 1,
        maxArgs: 1,
    },
    replaceOne: {
        fn: (args) => {
            return args[0].replace(args[1], args[2])
        },
        minArgs: 3,
        maxArgs: 3,
    },
    replaceAll: {
        fn: (args) => {
            return args[0].replaceAll(args[1], args[2])
        },
        minArgs: 3,
        maxArgs: 3,
    },
    position: {
        fn: ([str, elem]) => {
            if (typeof str === 'string') {
                return str.indexOf(String(elem)) + 1
            } else {
                return 0
            }
        },
        minArgs: 2,
        maxArgs: 2,
    },
    positionCaseInsensitive: {
        fn: ([str, elem]) => {
            if (typeof str === 'string') {
                return str.toLowerCase().indexOf(String(elem).toLowerCase()) + 1
            } else {
                return 0
            }
        },
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
        minArgs: 0,
        maxArgs: 0,
    },
    sha256Hex: {
        fn: ([str], _, options) => sha256Hex(str, options),
        minArgs: 1,
        maxArgs: 1,
    },
    md5Hex: {
        fn: ([str], _, options) => md5Hex(str, options),
        minArgs: 1,
        maxArgs: 1,
    },
    sha256HmacChainHex: {
        fn: ([data], _, options) => sha256HmacChainHex(data, options),
        minArgs: 1,
        maxArgs: 1,
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
        minArgs: 1,
        maxArgs: 1,
    },
    indexOf: {
        fn: ([arrOrString, elem]) => {
            if (Array.isArray(arrOrString)) {
                return arrOrString.indexOf(elem) + 1
            } else {
                return 0
            }
        },
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
        minArgs: 2,
        maxArgs: 2,
    },
    now: {
        fn: () => {
            return now()
        },
        minArgs: 0,
        maxArgs: 0,
    },
    toUnixTimestamp: {
        fn: (args) => {
            return toUnixTimestamp(args[0], args[1])
        },
        minArgs: 1,
        maxArgs: 2,
    },
    fromUnixTimestamp: {
        fn: (args) => {
            return fromUnixTimestamp(args[0])
        },
        minArgs: 1,
        maxArgs: 1,
    },
    toUnixTimestampMilli: {
        fn: (args) => {
            return toUnixTimestampMilli(args[0], args[1])
        },
        minArgs: 1,
        maxArgs: 2,
    },
    fromUnixTimestampMilli: {
        fn: (args) => {
            return fromUnixTimestampMilli(args[0])
        },
        minArgs: 1,
        maxArgs: 1,
    },
    toTimeZone: {
        fn: (args) => {
            return toTimeZone(args[0], args[1])
        },
        minArgs: 2,
        maxArgs: 2,
    },
    toDate: {
        fn: (args) => {
            return toDate(args[0])
        },
        minArgs: 1,
        maxArgs: 1,
    },
    toDateTime: {
        fn: (args) => {
            return toDateTime(args[0], args[1])
        },
        minArgs: 1,
        maxArgs: 2,
    },
    formatDateTime: {
        fn: (args) => {
            return formatDateTime(args[0], args[1], args[2])
        },
        minArgs: 2,
        maxArgs: 3,
    },
    HogError: {
        fn: (args) => newHogError(args[0], args[1], args[2]),
        minArgs: 1,
        maxArgs: 3,
    },
    Error: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
        minArgs: 0,
        maxArgs: 2,
    },
    RetryError: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
        minArgs: 0,
        maxArgs: 2,
    },
    NotImplementedError: {
        fn: (args, name) => newHogError(name, args[0], args[1]),
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
        minArgs: 1,
        maxArgs: 1,
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
