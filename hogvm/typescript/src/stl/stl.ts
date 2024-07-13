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
        return String(args[0])
    },
    toUUID: (args) => {
        return String(args[0])
    },
    toInt: (args) => {
        return !isNaN(parseInt(args[0])) ? parseInt(args[0]) : null
    },
    toFloat: (args) => {
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
            } else {
                return Object.keys(args[0]).length === 0
            }
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
                    if (typeof x === 'object' && Array.isArray(x)) {
                        return x.map((v) => convert(v, marked))
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
            } else {
                return Object.keys(obj)
            }
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
            } else {
                return Object.values(obj)
            }
        }
        return []
    },
}

export const ASYNC_STL: Record<string, (args: any[], name: string, timeout: number) => Promise<any>> = {
    sleep: async (args) => {
        await new Promise((resolve) => setTimeout(resolve, args[0] * 1000))
    },
}
