import { getExternalRequestConfig } from '~/common/config'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthHead, TruthPage } from '../provider-edge'

export type TruthRead = { limit?: number; timeoutMs?: number; atMostMs?: number; final?: boolean }

const FULL_PAGE_FROM_A_BUSY_EDGE_MS = 30_000

export interface TruthSource {
    head(read?: TruthRead): Promise<number>
    after(cursor: number, read?: TruthRead): Promise<TruthPage>
}

export class TruthReadCut extends Error {}

export type TruthBounds = { pollMs?: number; finalMs?: number }

export function edgeTruth(
    edgeUrl: string,
    { pollMs, finalMs = FULL_PAGE_FROM_A_BUSY_EDGE_MS }: TruthBounds = {}
): TruthSource {
    const get = async <T>(route: string, query: string, { timeoutMs, atMostMs, final }: TruthRead = {}): Promise<T> => {
        const bound = timeoutMs ?? (final ? finalMs : pollMs) ?? getExternalRequestConfig().EXTERNAL_REQUEST_TIMEOUT_MS
        const cut = atMostMs !== undefined && atMostMs < bound
        const response = await internalFetch(`${edgeUrl}${route}${query}`, {
            timeoutMs: cut ? atMostMs : bound,
        }).catch((error: unknown) => {
            throw cut && (error as { name?: unknown } | undefined)?.name === 'TimeoutError'
                ? new TruthReadCut(`The edge did not answer ${route} within ${atMostMs} ms`)
                : error
        })
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
