import equal from 'fast-deep-equal'

export function areObjectValuesEmpty(obj?: Record<string, any>): boolean {
    return (
        !!obj && typeof obj === 'object' && !Object.values(obj).some((x) => x !== null && x !== '' && x !== undefined)
    )
}

/** Compare objects deeply. */
export function objectsEqual(obj1: any, obj2: any): boolean {
    return equal(obj1, obj2)
}

// https://stackoverflow.com/questions/25421233/javascript-removing-undefined-fields-from-an-object
export function objectClean<T extends Record<string | number | symbol, unknown>>(
    obj: T,
    options?: { removeNulls?: boolean }
): T {
    const { removeNulls = false } = options || {}
    const response = { ...obj }
    Object.keys(response).forEach((key) => {
        if (removeNulls ? response[key] == null : response[key] === undefined) {
            delete response[key]
        }
    })
    return response
}
export function objectCleanWithEmpty<T extends Record<string | number | symbol, unknown>>(
    obj: T,
    ignoredKeys: string[] = []
): T {
    const response = { ...obj }
    Object.keys(response)
        .filter((key) => !ignoredKeys.includes(key))
        .forEach((key) => {
            // remove undefined values
            if (response[key] === undefined) {
                delete response[key]
            }
            // remove empty arrays i.e. []
            if (
                typeof response[key] === 'object' &&
                Array.isArray(response[key]) &&
                (response[key] as unknown[]).length === 0
            ) {
                delete response[key]
            }
            // remove empty objects i.e. {}
            if (
                typeof response[key] === 'object' &&
                !Array.isArray(response[key]) &&
                response[key] !== null &&
                Object.keys(response[key] as Record<string | number | symbol, unknown>).length === 0
            ) {
                delete response[key]
            }
        })
    return response
}

export const removeUndefinedAndNull = (obj: any): any => {
    if (Array.isArray(obj)) {
        return obj.map(removeUndefinedAndNull)
    } else if (obj && typeof obj === 'object') {
        return Object.entries(obj).reduce(
            (acc, [key, value]) => {
                if (value !== undefined && value !== null) {
                    acc[key] = removeUndefinedAndNull(value)
                }
                return acc
            },
            {} as Record<string, any>
        )
    }
    return obj
}

/** Returns "response" from: obj2 = { ...obj1, ...response }  */
export function objectDiffShallow(obj1: Record<string, any>, obj2: Record<string, any>): Record<string, any> {
    const response: Record<string, any> = { ...obj2 }
    for (const key of Object.keys(obj1)) {
        if (key in response) {
            if (obj1[key] === response[key]) {
                delete response[key]
            }
        } else {
            response[key] = undefined
        }
    }
    return response
}

export function idToKey(array: Record<string, any>[], keyField: string = 'id'): Record<string, any> {
    const object: Record<string, any> = {}
    for (const element of array) {
        object[element[keyField]] = element
    }
    return object
}

export function sortedKeys<T extends Record<string, any> = Record<string, any>>(object: T): T {
    const newObject: T = {} as T
    for (const key of Object.keys(object).sort()) {
        newObject[key as keyof T] = object[key]
    }
    return newObject
}

export function flattenObject<T extends Record<string, any>>(obj: T): Record<string, any> {
    return Object.entries(obj).reduce<Record<string, any>>((acc, [key, value]) => {
        if (value !== null && typeof value === 'object') {
            const flatChild = flattenObject(value)
            const normalizedKey = /^\d+$/.test(key) ? key.padStart(3, '0') : key

            Object.entries(flatChild).forEach(([subKey, subVal]) => {
                acc[`${normalizedKey}.${subKey}`] = subVal
            })
            return acc
        }

        acc[key] = value
        return acc
    }, {})
}

export function hasFormErrors(object: any): boolean {
    if (Array.isArray(object)) {
        return object.some(hasFormErrors)
    } else if (typeof object === 'object' && object !== null) {
        return Object.values(object).some(hasFormErrors)
    }
    return !!object
}
