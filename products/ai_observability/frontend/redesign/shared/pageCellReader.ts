import { objectsEqual } from 'lib/utils/objects'

import { CellLoads, rowsToRead } from './cellLoads'
import { createCellReader } from './cellReader'

// A kea logic's `cache`, which holds the reader's params, its refresh flag and the cell reader's latest reads.
type PageCellReaderCache = Record<string, any>

export type CellEntry<T> = [key: string, value: T]

export interface PageCellReaderOptions<Params, T> {
    cache: PageCellReaderCache
    /** The loads on screen, so a key in flight or already read is not asked for again. */
    loads: () => CellLoads<T>
    /** Drops every load, because new params ask every key a new question. */
    paramsChanged: () => void
    requested: (keys: string[]) => void
    failed: (keys: string[]) => void
    loaded: (entries: CellEntry<T>[]) => void
    request: (keys: string[], params: Params) => Promise<CellEntry<T>[]>
}

export interface PageCellReader<Params> {
    /** Keeps the loads of these params, and drops them for any other. */
    scopeTo: (params: Params) => void
    /** Reads the keys that have no load yet. */
    read: (keys: string[], params: Params) => Promise<void>
    /** The list started a reload, so the page it lands with is read again, keys already read included. */
    pageReloading: () => void
    pageFailed: () => void
    pageLoaded: (keys: string[], params: Params) => Promise<void>
}

/**
 * Reads a value for each key of a list's page, under params taken from the list's selection. A read for params that
 * are no longer current fills nothing and reports nothing, and only the latest read of a key may fill it.
 */
export function createPageCellReader<Params, T>({
    cache,
    loads,
    paramsChanged,
    requested,
    failed,
    loaded,
    request,
}: PageCellReaderOptions<Params, T>): PageCellReader<Params> {
    // Each change of params starts a new generation. The cell reader keys its latest reads by it, so a read for old
    // params never counts as the latest read of a key under the new ones.
    const isCurrent = (generation: string): boolean => generation === String(cache.paramsGeneration ?? 0)
    const readCells = createCellReader<string, string, CellEntry<T>>({
        cache,
        idOf: (key) => key,
        itemIdOf: ([key]) => key,
        requested: (_generation, keys) => requested(keys),
        failed: (generation, keys) => {
            if (isCurrent(generation)) {
                failed(keys)
            }
        },
    })

    const scopeTo = (params: Params): void => {
        if (!objectsEqual(params, cache.params)) {
            cache.params = params
            cache.paramsGeneration = (cache.paramsGeneration ?? 0) + 1
            paramsChanged()
        }
    }

    const readKeys = async (keys: string[], params: Params, refresh: boolean): Promise<void> => {
        scopeTo(params)
        const generation = String(cache.paramsGeneration ?? 0)
        await readCells(
            generation,
            rowsToRead(
                keys.map((id) => ({ id })),
                loads(),
                refresh
            ).map((row) => row.id),
            async (toRead) => ({ items: await request(toRead, params) }),
            (entries) => {
                if (isCurrent(generation)) {
                    loaded(entries)
                }
            }
        )
    }

    return {
        scopeTo,
        read: (keys, params) => readKeys(keys, params, false),
        pageReloading: () => {
            cache.refreshOnNextPage = true
        },
        pageFailed: () => {
            cache.refreshOnNextPage = false
        },
        pageLoaded: (keys, params) => {
            const refresh = !!cache.refreshOnNextPage
            cache.refreshOnNextPage = false
            return readKeys(keys, params, refresh)
        },
    }
}
