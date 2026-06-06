/** Make selected keys optional on a type while keeping all other keys unchanged. */
export type Optional<T, K extends keyof T> = Omit<T, K> & { [P in K]?: T[P] }

/** Make all keys of T required except those in K */
export type RequiredExcept<T, K extends keyof T> = {
    [P in Exclude<keyof T, K>]-?: T[P]
} & {
    [P in K]?: T[P]
}

/** Extract the value type from an array or object type. */
export type ValueOf<T> = T extends any[] ? T[number] : T[keyof T]
