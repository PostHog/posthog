import FuseClass, { IFuseOptions } from 'fuse.js'

export type Fuse<T> = FuseClass<T>
export type { IFuseOptions }

const FUSE_DEFAULTS = {
    threshold: 0.3,
    ignoreDiacritics: true,
}

export function createFuse<T>(items: T[], options: IFuseOptions<T>): FuseClass<T> {
    return new FuseClass<T>(items, { ...FUSE_DEFAULTS, ...options } as IFuseOptions<T>)
}

export type FuseSearch<T> = (items: T[], term: string) => T[]

export function createFuseSearch<T>(keys: (keyof T & string)[]): FuseSearch<T> {
    const fuse = createFuse<T>([], { keys })
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
