/** Make selected keys optional on a type while keeping all other keys unchanged. */
export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

/** Make all keys of T required except those in K */
export type RequiredExcept<T, K extends keyof T> = {
    [P in Exclude<keyof T, K>]-?: T[P]
} & {
    [P in K]?: T[P]
}

/** Extract the value type from an array or object type. */
export type ValueOf<a> = a extends any[] ? a[number] : a[keyof a]

/** Check whether a runtime key exists on an object and narrow it to `keyof T`. */
export function isKeyOf<T extends object>(key: any, obj: T): key is keyof T {
    return key in obj
}
