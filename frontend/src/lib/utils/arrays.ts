import { inStorybookTestRunner } from 'lib/utils/dom'

export function groupBy<T>(items: T[], groupResolver: (item: T) => string | number): Record<string | number, T[]> {
    const itemsGrouped: Record<string | number, T[]> = {}
    for (const item of items) {
        const group = groupResolver(item)
        if (!(group in itemsGrouped)) {
            itemsGrouped[group] = []
        } // Ensure there's an array to push to
        itemsGrouped[group].push(item)
    }
    return itemsGrouped
}

export function uniqueBy<T>(items: T[], uniqueResolver: (item: T) => any): T[] {
    const uniqueKeysSoFar = new Set<string>()
    const itemsUnique: T[] = []
    for (const item of items) {
        const uniqueKey = uniqueResolver(item)
        if (!uniqueKeysSoFar.has(uniqueKey)) {
            uniqueKeysSoFar.add(uniqueKey)
            itemsUnique.push(item)
        }
    }
    return itemsUnique
}

export function sample<T>(items: T[], size: number): T[] {
    if (!items.length) {
        throw Error('Items array is empty!')
    }
    if (size > items.length) {
        throw Error('Sample size cannot exceed items array length!')
    }
    const results: T[] = []
    const internalItems = [...items]
    if (size === items.length) {
        return internalItems
    }
    for (let i = 0; i < size; i++) {
        const index = Math.floor(Math.random() * internalItems.length)
        results.push(internalItems[index])
        internalItems.splice(index, 1)
    }
    return results
}

export function sampleOne<T>(items: T[]): T {
    if (!items.length) {
        throw Error('Items array is empty!')
    }
    const index = inStorybookTestRunner() ? 0 : Math.floor(Math.random() * items.length)
    return items[index]
}

// https://stackoverflow.com/questions/40929260/find-last-index-of-element-inside-array-by-certain-condition
export function findLastIndex<T>(array: Array<T>, predicate: (value: T, index: number, obj: T[]) => boolean): number {
    let l = array.length
    while (l--) {
        if (predicate(array[l], l, array)) {
            return l
        }
    }
    return -1
}

export function range(startOrEnd: number, end?: number): number[] {
    let length = startOrEnd
    let start = 0
    if (typeof end == 'number') {
        start = startOrEnd
        length = end - start
    }
    return Array.from({ length }, (_, i) => i + start)
}

// Split an array into consecutive sub-arrays of at most `size` items.
export function chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let i = 0; i < arr.length; i += size) {
        chunks.push(arr.slice(i, i + size))
    }
    return chunks
}

export function interleave(arr: any[], delimiter: any): any[] {
    return arr.flatMap((item, index, _arr) =>
        _arr.length - 1 !== index // check for the last item
            ? [item, delimiter]
            : item
    )
}

export function interleaveArray<T1, T2>(arr: T1[], separator: T2): (T1 | T2)[] {
    return arr.flatMap((item, index, _arr) => (_arr.length - 1 !== index ? [item, separator] : [item]))
}
