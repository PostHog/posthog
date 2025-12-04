export type StringInterner = (str: string) => string

export const createStringInterner = (): StringInterner => {
    const cache = new Map<string, string>()
    return (str: string): string => {
        const cached = cache.get(str)
        if (cached !== undefined) {
            return cached
        }
        cache.set(str, str)
        return str
    }
}

export const internedReviver =
    (intern: StringInterner) =>
    (_key: string, value: unknown): unknown =>
        typeof value === 'string' ? intern(value) : value
