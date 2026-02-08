/**
 * Sometimes you want to try catch a simple function in a single assignment and this function helps you do that
 * So instead of:
 *
 * let result: T
 * try {
 *     result = await fn()
 * } catch (e) {
 *     result = e
 * }
 *
 * you can do:
 *
 * const [error, result] = await tryCatch(fn)
 */

export async function tryCatch<T>(fn: () => Promise<T>): Promise<[Error | null, T | null]> {
    try {
        const result = await fn()
        return [null, result]
    } catch (e) {
        return [e, null]
    }
}

export function tryCatchSync<T>(fn: () => T): [Error | null, T | null] {
    try {
        const result = fn()
        return [null, result]
    } catch (e) {
        return [e, null]
    }
}
