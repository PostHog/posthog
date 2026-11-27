import { readOrFailure } from './readOrFailure'

// A kea logic's `cache`, which carries the disposables manager the read checks after an unmount.
type CellReaderCache = Record<string, any>

export interface CellReaderOptions<Row, Read extends string, Item> {
    cache: CellReaderCache
    idOf: (row: Row) => string
    /** The id of the row an answered item fills, the same id `idOf` gives that row. */
    itemIdOf: (item: Item) => string
    requested: (read: Read, ids: string[]) => void
    failed: (read: Read, ids: string[]) => void
}

/**
 * Reads one kind of cell for some rows. A refresh reads rows that are already on screen, so two reads of one row can
 * overlap. Only the latest read of a row may fill it, or an older answer that lands last would overwrite a newer one.
 */
export function createCellReader<Row, Read extends string, Item>({
    cache,
    idOf,
    itemIdOf,
    requested,
    failed,
}: CellReaderOptions<Row, Read, Item>): <ReadItem extends Item>(
    read: Read,
    rows: Row[],
    request: (rows: Row[]) => Promise<{ items: ReadItem[] }>,
    loaded: (items: ReadItem[]) => void
) => Promise<void> {
    const latestReads: Map<string, number> = (cache.latestCellReads ??= new Map())
    const readKey = (read: Read, id: string): string => `${read}:${id}`

    return async (read, rows, request, loaded) => {
        if (rows.length === 0) {
            return
        }
        const ids = rows.map(idOf)
        const readId = (cache.lastCellReadId = (cache.lastCellReadId ?? 0) + 1)
        for (const id of ids) {
            latestReads.set(readKey(read, id), readId)
        }
        requested(read, ids)
        const result = await readOrFailure(request(rows))
        if (cache.disposables.isDisposed) {
            return
        }
        if ('failure' in result) {
            failed(read, ids)
        } else {
            loaded(result.value.items.filter((item) => latestReads.get(readKey(read, itemIdOf(item))) === readId))
        }
    }
}
