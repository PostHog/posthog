export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

/** Make all keys of T required except those in K */
export type RequiredExcept<T, K extends keyof T> = {
    [P in Exclude<keyof T, K>]-?: T[P]
} & {
    [P in K]?: T[P]
}

export type ValueOf<a> = a extends any[] ? a[number] : a[keyof a]
export type Values<a extends object> = UnionToTuple<ValueOf<a>>
