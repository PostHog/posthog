import { z } from 'zod'

import type { PostHogApi } from './api'

// HogQLQueryResponse declares `columns` and `types` optional.
const HogQLResponse = z.looseObject({
    columns: z.array(z.string()).nullish(),
    types: z.array(z.tuple([z.string(), z.string()])).nullish(),
    results: z.array(z.array(z.unknown())),
    hasMore: z.boolean().nullish(),
})

export type HogQLResponse = z.output<typeof HogQLResponse>

// Needs the `query:read` scope.
export function runHogQL(api: PostHogApi, query: string, options: { timeoutMs?: number } = {}): Promise<HogQLResponse> {
    return api.post('query', { query: { kind: 'HogQLQuery', query }, refresh: 'blocking' }, HogQLResponse, options)
}
