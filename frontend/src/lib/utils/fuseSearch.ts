import FuseClass from 'fuse.js'

export type FuseSearch<T> = (items: T[], term: string) => T[]

export function createFuseSearch<T>(keys: (keyof T & string)[], threshold = 0.3): FuseSearch<T> {
    const fuse = new FuseClass<T>([], { keys, threshold })
    return (items: T[], term: string): T[] => {
        if (!term.trim()) {
            return items
        }
        fuse.setCollection(items)
        return fuse.search(term).map((r) => r.item)
    }
}

export function createFeaturePreviewSearch<
    T extends { name: string; description: string; stage: string },
>(): FuseSearch<T> {
    return createFuseSearch<T>(['name', 'description', 'stage'])
}
