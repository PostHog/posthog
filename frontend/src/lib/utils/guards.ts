import { ActorType, GroupActorType, SessionActorType } from '~/types'

export function isString(candidate: unknown): candidate is string {
    return typeof candidate === 'string'
}

export function isNumber(candidate: unknown): candidate is number {
    return typeof candidate === 'number'
}

export function isObject(candidate: unknown): candidate is Record<string, unknown> {
    return typeof candidate === 'object' && candidate !== null && !Array.isArray(candidate)
}

export function isEmptyObject(candidate: unknown): boolean {
    return isObject(candidate) && Object.keys(candidate).length === 0
}

export function isNonEmptyObject(candidate: unknown): candidate is Record<string, unknown> {
    return isObject(candidate) && !isEmptyObject(candidate)
}

/** Check whether a runtime key exists on an object and narrow it to `keyof T`. */
export function isKeyOf<T extends object>(key: any, obj: T): key is keyof T {
    return key in obj
}

/**
 * Check if the argument is not nullish (null or undefined).
 *
 * Useful as a typeguard, e.g. when passed to Array.filter()
 *
 * @example
 * const myList = [1, 2, null]; // type is (number | null)[]
 *
 * // using isNotNil
 * const myFilteredList1 = myList.filter(isNotNil) // type is number[]
 * const squaredList1 = myFilteredList1.map(x => x * x) // not a type error!
 *
 * // compared to:
 * const myFilteredList2 = myList.filter(x => x != null) // type is (number | null)[]
 * const squaredList2 = myFilteredList2.map(x => x * x) // Type Error: TS18047: x is possibly null
 */
export function isNotNil<T>(arg: T): arg is Exclude<T, null | undefined> {
    return arg !== null && arg !== undefined
}

// https://stackoverflow.com/questions/175739/how-can-i-check-if-a-string-is-a-valid-number
export function isNumeric(x: unknown): x is number {
    if (typeof x === 'number') {
        return !isNaN(x) && isFinite(x)
    }
    if (typeof x !== 'string' || x.trim() === '') {
        return false
    }
    return !isNaN(Number(x))
}

/**
 * Checks if a string matches the canonical UUID/UUID-like format.
 *
 * This function only checks the structure:
 *  - 8-4-4-4-12 hexadecimal characters
 *  - 4 dashes in the correct positions
 * It does not enforce UUID version or variant.
 *
 * Examples:
 *  - ✅ "0199ed4a-5c03-0000-3220-df21df612e95"
 *  - ❌ "not-a-uuid"
 *
 * @param candidate - The string to test.
 * @returns True if the string matches the UUID-like structure.
 */
export function isUUIDLike(candidate: string): boolean {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(candidate)
}

export function isGroupType(actor: ActorType): actor is GroupActorType {
    return actor.type === 'group'
}

export function isSessionType(actor: ActorType): actor is SessionActorType {
    return actor.type === 'session'
}

/** An error signaling that a value of type `never` in TypeScript was used unexpectedly at runtime.
 *
 * Useful for type-narrowing, will give a compile-time error if the type of x is not `never`.
 * See the example below where it catches a missing branch at compile-time.
 *
 * @example
 *
 * enum MyEnum {
 *     a,
 *     b,
 * }
 *
 * function handleEnum(x: MyEnum) {
 *     switch (x) {
 *         case MyEnum.a:
 *             return
 *         // missing branch
 *         default:
 *             throw new UnexpectedNeverError(x) // TS2345: Argument of type MyEnum is not assignable to parameter of type never
 *     }
 * }
 *
 * function handleEnum(x: MyEnum) {
 *     switch (x) {
 *         case MyEnum.a:
 *             return
 *         case MyEnum.b:
 *             return
 *         default:
 *             throw new UnexpectedNeverError(x) // no type error
 *     }
 * }
 *
 */
export class UnexpectedNeverError extends Error {
    constructor(x: never, message?: string) {
        message = message ?? 'Unexpected never: ' + String(x)
        super(message)

        // restore prototype chain, which is broken by Error
        // see https://stackoverflow.com/questions/41102060/typescript-extending-error-class
        const actualProto = new.target.prototype
        if (Object.setPrototypeOf) {
            Object.setPrototypeOf(this, actualProto)
        }
    }
}

/**
 * Assigns a value to an object field while preserving key-based type inference.
 * Use this when the key is known but the incoming value is `unknown` and has
 * already been validated by surrounding logic.
 *
 * @param obj - Object to mutate.
 * @param key - Field name to assign on `obj`.
 * @param value - Value to assign; cast to `T[K]`.
 * @returns {void}
 */
export function assignField<T, K extends keyof T>(obj: T, key: K, value: unknown): void {
    obj[key] = value as T[K]
}
