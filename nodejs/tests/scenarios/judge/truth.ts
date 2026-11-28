import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import type { TruthHead, TruthPage } from '../provider-edge'

export type TruthRead = { limit?: number; timeoutMs?: number; final?: boolean; waitMs?: number }

const FULL_PAGE_FROM_A_BUSY_EDGE_MS = 30_000
const HEAD_ANSWERS_WITHIN_MS = 1000

export interface TruthSource {
    head(read?: TruthRead): Promise<number>
    after(cursor: number, read?: TruthRead): Promise<TruthPage>
    feedbackInFlight?(): number
}

export type TruthBounds = { pollMs?: number; finalMs?: number }

export function edgeTruth(
    edgeUrl: string,
    { pollMs, finalMs = FULL_PAGE_FROM_A_BUSY_EDGE_MS }: TruthBounds = {}
): TruthSource {
    let inFlight = 0
    const boundOf = ({ timeoutMs, final }: TruthRead): number | undefined => timeoutMs ?? (final ? finalMs : pollMs)
    const get = async <T>(route: string, query: string, bound: number | undefined): Promise<T> => {
        const response = await internalFetch(`${edgeUrl}${route}${query}`, bound ? { timeoutMs: bound } : undefined)
        if (response.status !== 200) {
            throw new Error(`The edge answered ${route} with ${response.status}`)
        }
        return parseJSON(await response.text()) as T
    }
    return {
        head: async (read = {}) => {
            const waitMs = read.waitMs ?? (read.final ? Math.max(0, (boundOf(read) ?? 0) - HEAD_ANSWERS_WITHIN_MS) : 0)
            const bound = read.waitMs === undefined ? boundOf(read) : waitMs + HEAD_ANSWERS_WITHIN_MS
            const answered = await get<TruthHead>('/_truth/head', waitMs > 0 ? `?waitMs=${waitMs}` : '', bound)
            inFlight = answered.feedbackInFlight ?? 0
            return answered.head
        },
        after: (cursor, read = {}) =>
            get<TruthPage>('/_truth', `?after=${cursor}${read.limit ? `&limit=${read.limit}` : ''}`, boundOf(read)),
        feedbackInFlight: () => inFlight,
    }
}
