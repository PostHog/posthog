import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthHead, TruthPage } from '../provider-edge'

export type TruthRead = { limit?: number; timeoutMs?: number }

// A full page is a thousand records with their messages, served by an edge whose one event loop also answers sends.
const TRUTH_PAGE_TIMEOUT_MS = 30_000

export interface TruthSource {
    head(read?: TruthRead): Promise<number>
    after(cursor: number, read?: TruthRead): Promise<TruthPage>
}

export function edgeTruth(edgeUrl: string, pageTimeoutMs = TRUTH_PAGE_TIMEOUT_MS): TruthSource {
    const get = async <T>(route: string, query: string, { timeoutMs = pageTimeoutMs }: TruthRead = {}): Promise<T> => {
        const response = await internalFetch(`${edgeUrl}${route}${query}`, { timeoutMs })
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
