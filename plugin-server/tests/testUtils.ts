/**
 * Recursively freeze an object and all its properties.
 *
 * The most common use case for this is to test that a function does not mutate its arguments. A frozen
 * object will throw an error if any of its properties are modified.
 */
export function deepFreeze<T extends object>(t: T): T {
    function deepFreezeInner(obj: any) {
        if (obj === null || typeof obj !== 'object') {
            return
        }
        if (Object.isFrozen(obj)) {
            return
        }
        Object.freeze(obj)
        Object.keys(obj).forEach((key) => {
            if (key in obj) {
                deepFreezeInner(obj[key])
            }
        })
        return obj
    }
    deepFreezeInner(t)
    return t
}
