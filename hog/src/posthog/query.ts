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
// `force_blocking` skips PostHog's cache, for a query whose answer has to be current.
export function runHogQL(
    api: PostHogApi,
    query: string,
    options: { timeoutMs?: number; refresh?: 'blocking' | 'force_blocking' } = {}
): Promise<HogQLResponse> {
    const { refresh = 'blocking', timeoutMs } = options
    return api.post('query', { query: { kind: 'HogQLQuery', query }, refresh }, HogQLResponse, { timeoutMs })
}
