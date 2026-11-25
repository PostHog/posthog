import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthHead, TruthPage } from '../provider-edge'

export type TruthRead = { limit?: number; timeoutMs?: number; final?: boolean }

const FULL_PAGE_FROM_A_BUSY_EDGE_MS = 30_000

export interface TruthSource {
    head(read?: TruthRead): Promise<number>
    after(cursor: number, read?: TruthRead): Promise<TruthPage>
}

export type TruthBounds = { pollMs?: number; finalMs?: number }

export function edgeTruth(
    edgeUrl: string,
    { pollMs, finalMs = FULL_PAGE_FROM_A_BUSY_EDGE_MS }: TruthBounds = {}
): TruthSource {
    const get = async <T>(route: string, query: string, { timeoutMs, final }: TruthRead = {}): Promise<T> => {
        const bound = timeoutMs ?? (final ? finalMs : pollMs)
        const response = await internalFetch(`${edgeUrl}${route}${query}`, bound ? { timeoutMs: bound } : undefined)
        if (response.status !== 200) {
            throw new Error(`The edge answered ${route} with ${response.status}`)
        }
        return parseJSON(await response.text()) as T
    }
    return {
        head: async (read) => (await get<TruthHead>('/_truth/head', '', read)).head,
        after: (cursor, read = {}) =>
            get<TruthPage>('/_truth', `?after=${cursor}${read.limit ? `&limit=${read.limit}` : ''}`, read),
    }
}
