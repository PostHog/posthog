import { toHogDate, toHogDateTime } from './stl/date'

export class HogVMException extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'HogVMException'
    }
}

export class UncaughtHogVMException extends HogVMException {
    type: any
    payload: any

    constructor(type: string, message: string, payload: any = null) {
        super(message)
        this.name = 'UncaughtHogVMException'
        this.type = type
        this.payload = payload
    }

    toString(): string {
        const msg = this.message.replaceAll("'", "\\'")
        return `${this.type}('${msg}')`
    }
}

/** Fixed cost per object in memory */
const COST_PER_UNIT = 8

export function like(
    string: string,
    pattern: string,
    caseInsensitive = false,
    match?: (regex: string, value: string) => boolean
): boolean {
    pattern = String(pattern)
        .replaceAll(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
        .replaceAll('%', '.*')
        .replaceAll('_', '.')
    if (match) {
        return match((caseInsensitive ? '(?i)' : '') + pattern, string)
    }
    return new RegExp(pattern, caseInsensitive ? 'i' : undefined).test(string)
}
export function getNestedValue(obj: any, chain: any[], nullish = false): any {
    if (typeof obj === 'object' && obj !== null) {
        for (const key of chain) {
            if (nullish && obj === null) {
                return null
            }
            // if obj is a map
            if (obj instanceof Map) {
                obj = obj.get(key) ?? null
            } else if (typeof key === 'number') {
                if (key == 0) {
                    throw new Error(`Hog arrays start from index 1`)
                } else if (key > 0) {
                    obj = obj[key - 1] ?? null
                } else {
                    obj = obj[obj.length + key] ?? null
                }
            } else {
                obj = obj[key] ?? null
            }
        }
        return obj
    }
    return null
}
export function setNestedValue(obj: any, chain: any[], value: any): void {
    if (typeof obj !== 'object' || obj === null) {
        throw new Error(`Can not set ${chain} on non-object: ${typeof obj}`)
    }
    for (let i = 0; i < chain.length - 1; i++) {
        const key = chain[i]
        if (obj instanceof Map) {
            obj = obj.get(key) ?? null
        } else if (Array.isArray(obj) && typeof key === 'number') {
            if (key <= 0) {
                throw new Error(`Hog arrays start from index 1`)
            }
            obj = obj[key - 1]
        } else {
            throw new Error(`Can not get ${chain} on element of type ${typeof obj}`)
        }
    }
    const lastKey = chain[chain.length - 1]
    if (obj instanceof Map) {
        obj.set(lastKey, value)
    } else if (Array.isArray(obj) && typeof lastKey === 'number') {
        if (lastKey <= 0) {
            throw new Error(`Hog arrays start from index 1`)
        }
        obj[lastKey - 1] = value
    } else {
        throw new Error(`Can not set ${chain} on element of type ${typeof obj}`)
    }
}

// Recursively convert objects to maps
export function convertJSToHog(x: any, found?: Map<any, any>): any {
    if (!found) {
        found = new Map()
    }
    if (found.has(x)) {
        return found.get(x)
    }
    if (Array.isArray(x)) {
        const obj: any[] = []
        found.set(x, obj)
        x.forEach((v) => obj.push(convertJSToHog(v, found)))
        found.delete(x)
        return obj
    } else if (typeof x === 'object' && x !== null) {
        if (x.__hogDateTime__) {
            return toHogDateTime(x.dt, x.zone)
        } else if (x.__hogDate__) {
            return toHogDate(x.year, x.month, x.day)
        } else if (x.__hogClosure__ || x.__hogCallable__) {
            return x
        }
        const map = new Map()
        found.set(x, map)
        for (const key in x) {
            map.set(key, convertJSToHog(x[key], found))
        }
        found.delete(x)
        return map
    }
    return x
}

export function convertHogToJS(x: any, found?: Map<any, any>): any {
    if (!found) {
        found = new Map()
    }
    if (found.has(x)) {
        return found.get(x)
    }
    if (x instanceof Map) {
        const obj: Record<string, any> = {}
        found.set(x, obj)
        x.forEach((value, key) => {
            obj[key] = convertHogToJS(value, found)
        })
        found.delete(x)
        return obj
    } else if (typeof x === 'object' && Array.isArray(x)) {
        const obj: any[] = []
        found.set(x, obj)
        x.forEach((v) => obj.push(convertHogToJS(v, found)))
        found.delete(x)
        return obj
    } else if (typeof x === 'object' && x !== null) {
        if (x.__hogDateTime__ || x.__hogDate__ || x.__hogClosure__ || x.__hogCallable__) {
            return x
        }
        const obj: Record<string, any> = {}
        found.set(x, obj)
        for (const key in x) {
            obj[key] = convertHogToJS(x[key], found)
        }
        found.delete(x)
        return obj
    }
    return x
}

export function calculateCost(object: any, marked: Set<any> | undefined = undefined): any {
    if (!marked) {
        marked = new Set()
    }
    if (typeof object === 'object' && object !== null) {
        if (marked.has(object)) {
            return COST_PER_UNIT
        }
        marked.add(object)
        try {
            if (object instanceof Map) {
                return (
                    COST_PER_UNIT +
                    Array.from(object.keys()).reduce(
                        (acc, key) => acc + calculateCost(key, marked) + calculateCost(object.get(key), marked),
                        0
                    )
                )
            } else if (Array.isArray(object)) {
                return COST_PER_UNIT + object.reduce((acc, val) => acc + calculateCost(val, marked), 0)
            }
            return (
                COST_PER_UNIT +
                Object.keys(object).reduce(
                    (acc, key) => acc + calculateCost(key, marked) + calculateCost(object[key], marked),
                    0
                )
            )
        } finally {
            marked.delete(object)
        }
    } else if (typeof object === 'string') {
        return COST_PER_UNIT + object.length
    }
    return COST_PER_UNIT
}

export function unifyComparisonTypes(left: any, right: any): [any, any] {
    if (typeof left === 'number' && typeof right === 'string') {
        return [left, Number(right)]
    }
    if (typeof left === 'string' && typeof right === 'number') {
        return [Number(left), right]
    }
    if (typeof left === 'boolean' && typeof right === 'string') {
        return [left, right === 'true']
    }
    if (typeof left === 'string' && typeof right === 'boolean') {
        return [left === 'true', right]
    }
    if (typeof left === 'boolean' && typeof right === 'number') {
        return [left ? 1 : 0, right]
    }
    if (typeof left === 'number' && typeof right === 'boolean') {
        return [left, right ? 1 : 0]
    }
    return [left, right]
}
