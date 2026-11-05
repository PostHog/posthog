import { z } from 'zod'

import type { PostHogApi } from '@/posthog/api'

import { Endpoint, InsightVariable } from './model'

// Follows `next` links, so a project with more endpoints than one page holds still gets all of them.
async function all<S extends z.ZodType>(api: PostHogApi, path: string, item: S): Promise<z.output<S>[]> {
    const page = z.looseObject({ results: z.array(item), next: z.string().nullish() })
    const results: z.output<S>[] = []
    let next: string | null | undefined = path
    while (next) {
        const current: { results: z.output<S>[]; next?: string | null } = await api.get(next, page)
        results.push(...current.results)
        next = current.next ? new URL(current.next).pathname + new URL(current.next).search : undefined
    }
    return results
}

export function listEndpoints(api: PostHogApi): Promise<Endpoint[]> {
    return all(api, 'endpoints/', Endpoint)
}

export function getEndpoint(api: PostHogApi, name: string): Promise<Endpoint> {
    return api.get(`endpoints/${encodeURIComponent(name)}/`, Endpoint)
}

// PostHog allows a variable without a code name, which no query can reference, so the list leaves
// it out.
const ListedVariable = InsightVariable.extend({ code_name: z.string().nullable() })

export async function listInsightVariables(api: PostHogApi): Promise<InsightVariable[]> {
    const variables = await all(api, 'insight_variables/', ListedVariable)
    return variables.flatMap(({ code_name, ...variable }) => (code_name === null ? [] : [{ ...variable, code_name }]))
}

export function createInsightVariable(
    api: PostHogApi,
    variable: { code_name: string; type: string; default_value?: unknown; is_multi?: boolean }
): Promise<InsightVariable> {
    return api.post('insight_variables/', { name: variable.code_name, ...variable }, InsightVariable)
}

export function createEndpoint(api: PostHogApi, body: Record<string, unknown>): Promise<Endpoint> {
    return api.post('endpoints/', body, Endpoint)
}

export function updateEndpoint(api: PostHogApi, name: string, body: Record<string, unknown>): Promise<Endpoint> {
    return api.patch(`endpoints/${encodeURIComponent(name)}/`, body, Endpoint)
}
