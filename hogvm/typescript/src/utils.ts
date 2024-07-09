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
        const obj: Record<string, any> = {}
        for (const key in x) {
            obj[key] = convertHogToJS(x[key])
        }
        return obj
    }
    return x
}

export function calculateCost(object: any): any {
    if (object instanceof Map) {
        return (
            COST_PER_UNIT +
            Array.from(object.keys()).reduce((acc, key) => acc + calculateCost(key) + calculateCost(object.get(key)), 0)
        )
    } else if (typeof object === 'object') {
        if (Array.isArray(object)) {
            return COST_PER_UNIT + object.reduce((acc, val) => acc + calculateCost(val), 0)
        } else if (object === null) {
            return COST_PER_UNIT
        } else {
            return (
                COST_PER_UNIT +
                Object.keys(object).reduce((acc, key) => acc + calculateCost(key) + calculateCost(object[key]), 0)
            )
        }
    } else if (typeof object === 'string') {
        return COST_PER_UNIT + object.length
    } else if (typeof object === 'number') {
        return COST_PER_UNIT
    } else {
        return COST_PER_UNIT
    }
}
