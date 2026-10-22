export function lazyMap<T, U>(source: readonly T[], mapper: (value: T, index: number) => U): U[] {
    const mapped = new Set<number>()
    const target = Array.from<U>({ length: source.length })

    return new Proxy(target, {
        get(array, property, receiver) {
            if (typeof property !== 'string' || !/^(0|[1-9]\d*)$/.test(property)) {
                return Reflect.get(array, property, receiver)
            }

            const index = Number(property)
            if (index < source.length && property in array && !mapped.has(index)) {
                array[index] = mapper(source[index], index)
                mapped.add(index)
            }
            return array[index]
        },
        set(array, property, value, receiver) {
            if (typeof property === 'string' && /^(0|[1-9]\d*)$/.test(property)) {
                mapped.add(Number(property))
            }
            return Reflect.set(array, property, value, receiver)
        },
    })
}
