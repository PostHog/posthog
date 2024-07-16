import { DateTime } from 'luxon'

import {
    fromUnixTimestamp,
    fromUnixTimestampMilli,
    isHogDate,
    isHogDateTime,
    now,
    toDate,
    toDateTime,
    toHogDate,
    toHogDateTime,
    toTimeZone,
    toUnixTimestamp,
    toUnixTimestampMilli,
    formatDateTime,
} from './date'
import { printHogStringOutput } from './print'

export const STL: Record<string, (args: any[], name: string, timeout: number) => any> = {
    concat: (args) => {
        return args.map((arg: any) => (arg === null ? '' : String(arg))).join('')
    },
    match: (args) => {
        const regex = new RegExp(args[1])
        return regex.test(args[0])
    },
    toString: (args: any[]) => {
        if (isHogDate(args[0])) {
            const month = args[0].month
            const day = args[0].day
            return `${args[0].year}-${month < 10 ? '0' : ''}${month}-${day < 10 ? '0' : ''}${day}`
        }
        if (isHogDateTime(args[0])) {
            return DateTime.fromSeconds(args[0].dt, { zone: args[0].zone }).toISO()
        }
        return String(args[0])
    },
    toUUID: (args) => {
        return String(args[0])
    },
    toInt: (args) => {
        if (isHogDateTime(args[0])) {
            return Math.floor(args[0].dt)
        } else if (isHogDate(args[0])) {
            const day = DateTime.fromObject({ year: args[0].year, month: args[0].month, day: args[0].day })
            const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
            return Math.floor(day.diff(epoch, 'days').days)
        }
        return !isNaN(parseInt(args[0])) ? parseInt(args[0]) : null
    },
    toFloat: (args) => {
        if (isHogDateTime(args[0])) {
            return args[0].dt
        } else if (isHogDate(args[0])) {
            const day = DateTime.fromObject({ year: args[0].year, month: args[0].month, day: args[0].day })
            const epoch = DateTime.fromObject({ year: 1970, month: 1, day: 1 })
            return Math.floor(day.diff(epoch, 'days').days)
        }
        return !isNaN(parseFloat(args[0])) ? parseFloat(args[0]) : null
    },
    // ifNull is complied into JUMP instructions. Keeping the function here for backwards compatibility
    ifNull: (args) => {
        return args[0] !== null ? args[0] : args[1]
    },
    length: (args) => {
        return args[0].length
    },
    empty: (args) => {
        if (typeof args[0] === 'object') {
            if (Array.isArray(args[0])) {
                return args[0].length === 0
            } else if (args[0] === null) {
                return true
            } else if (args[0] instanceof Map) {
                return args[0].size === 0
            }
            return Object.keys(args[0]).length === 0
        }
        return !args[0]
    },
    notEmpty: (args) => {
        return !STL.empty(args, 'empty', 0)
    },
    tuple: (args) => {
        const tuple = args.slice()
        ;(tuple as any).__isHogTuple = true
        return tuple
    },
    lower: (args) => {
        return args[0].toLowerCase()
    },
    upper: (args) => {
        return args[0].toUpperCase()
    },
    reverse: (args) => {
        return args[0].split('').reverse().join('')
    },
    print: (args) => {
        // eslint-disable-next-line no-console
        console.log(...args.map(printHogStringOutput))
    },
    jsonParse: (args) => {
        // Recursively convert objects to maps
        function convert(x: any): any {
            if (Array.isArray(x)) {
                return x.map(convert)
            } else if (typeof x === 'object' && x !== null) {
                // Date and DateTime will not be converted to a map
                if (x.__hogDateTime__) {
                    return toHogDateTime(x.dt, x.zone)
                } else if (x.__hogDate__) {
                    return toHogDate(x.year, x.month, x.day)
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
    jsonStringify: (args) => {
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
                    if (isHogDateTime(x) || isHogDate(x)) {
                        return x
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
    base64Encode: (args) => {
        return Buffer.from(args[0]).toString('base64')
    },
    base64Decode: (args) => {
        return Buffer.from(args[0], 'base64').toString()
    },
    tryBase64Decode: (args) => {
        try {
            return Buffer.from(args[0], 'base64').toString()
        } catch (e) {
            return ''
        }
    },
    encodeURLComponent(args) {
        return encodeURIComponent(args[0])
    },
    decodeURLComponent(args) {
        return decodeURIComponent(args[0])
    },
    replaceOne(args) {
        return args[0].replace(args[1], args[2])
    },
    replaceAll(args) {
        return args[0].replaceAll(args[1], args[2])
    },
    generateUUIDv4() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = (Math.random() * 16) | 0
            const v = c === 'x' ? r : (r & 0x3) | 0x8
            return v.toString(16)
        })
    },
    keys(args) {
        const obj = args[0]
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
    values(args) {
        const obj = args[0]
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
    now() {
        return now()
    },
    toUnixTimestamp(args) {
        return toUnixTimestamp(args[0], args[1])
    },
    fromUnixTimestamp(args) {
        return fromUnixTimestamp(args[0])
    },
    toUnixTimestampMilli(args) {
        return toUnixTimestampMilli(args[0], args[1])
    },
    fromUnixTimestampMilli(args) {
        return fromUnixTimestampMilli(args[0])
    },
    toTimeZone(args) {
        return toTimeZone(args[0], args[1])
    },
    toDate(args) {
        return toDate(args[0])
    },
    toDateTime(args) {
        return toDateTime(args[0], args[1])
    },
    formatDateTime(args) {
        return formatDateTime(args[0], args[1], args[2])
    },
}

export const ASYNC_STL: Record<string, (args: any[], name: string, timeout: number) => Promise<any>> = {
    sleep: async (args) => {
        await new Promise((resolve) => setTimeout(resolve, args[0] * 1000))
    },
}
