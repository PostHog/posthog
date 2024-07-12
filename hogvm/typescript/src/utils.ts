import { toHogDate, toHogDateTime } from './stl/date'

/** Fixed cost per object in memory */
const COST_PER_UNIT = 8

export function like(string: string, pattern: string, caseInsensitive = false): boolean {
    pattern = String(pattern)
        .replaceAll(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')
        .replaceAll('%', '.*')
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
                obj = obj[key] ?? null
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
            obj = obj[key]
        } else {
            throw new Error(`Can not get ${chain} on element of type ${typeof obj}`)
        }
    }
    const lastKey = chain[chain.length - 1]
    if (obj instanceof Map) {
        obj.set(lastKey, value)
    } else if (Array.isArray(obj) && typeof lastKey === 'number') {
        obj[lastKey] = value
    } else {
        throw new Error(`Can not set ${chain} on element of type ${typeof obj}`)
    }
}

// Recursively convert objects to maps
export function convertJSToHog(x: any): any {
    if (Array.isArray(x)) {
        return x.map(convertJSToHog)
    } else if (typeof x === 'object' && x !== null) {
        if (x.__hogDateTime__) {
            return toHogDateTime(x.dt, x.zone)
        } else if (x.__hogDate__) {
            return toHogDate(x.year, x.month, x.day)
        }
        const map = new Map()
        for (const key in x) {
            map.set(key, convertJSToHog(x[key]))
        }
        return map
    }
    return x
}

export function convertHogToJS(x: any): any {
    if (x instanceof Map) {
        const obj: Record<string, any> = {}
        x.forEach((value, key) => {
            obj[key] = convertHogToJS(value)
        })
        return obj
    } else if (typeof x === 'object' && Array.isArray(x)) {
        return x.map(convertHogToJS)
    } else if (typeof x === 'object' && x !== null) {
        if (x.__hogDateTime__) {
            return {
                __hogDateTime__: true,
                dt: x.dt.toMillis(),
                zone: x.dt.zone.name,
            }
        } else if (x.__hogDate__) {
            return {
                __hogDate__: true,
                year: x.year,
                month: x.month,
                day: x.day,
                zone: x.zone,
            }
        }
        const obj: Record<string, any> = {}
        for (const key in x) {
            obj[key] = convertHogToJS(x[key])
        }
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
