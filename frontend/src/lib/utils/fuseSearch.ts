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
        // Trim before searching: leading/trailing whitespace changes the pattern length
        // and inflates Fuse's effective edit budget (threshold × length), which lets
        // unrelated items match (e.g. "mcp " picks up "Map clicked", "SMTP delivered").
        const trimmed = term.trim()
        if (!trimmed) {
            return items
        }
        fuse.setCollection(items)
        return fuse.search(trimmed).map((r) => r.item)
    }
}

export function createFeaturePreviewSearch<
    T extends { name: string; description: string; stage: string },
>(): FuseSearch<T> {
    return createFuseSearch<T>(['name', 'description', 'stage'])
}
