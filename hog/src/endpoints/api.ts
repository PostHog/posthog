import type { PostHogApi } from '@/posthog/api'

import type { Endpoint, InsightVariable } from './model'

interface Page<T> {
    results: T[]
    next?: string | null
}

// Follows `next` links, so a project with more endpoints than one page holds still gets all of them.
async function all<T>(api: PostHogApi, path: string): Promise<T[]> {
    const results: T[] = []
    let next: string | null | undefined = path
    while (next) {
        const page: Page<T> = await api.get<Page<T>>(next)
        results.push(...page.results)
        next = page.next ? new URL(page.next).pathname + new URL(page.next).search : undefined
    }
    return results
}

export function listEndpoints(api: PostHogApi): Promise<Endpoint[]> {
    return all<Endpoint>(api, 'endpoints/')
}

export function getEndpoint(api: PostHogApi, name: string): Promise<Endpoint> {
    return api.get<Endpoint>(`endpoints/${encodeURIComponent(name)}/`)
}

export function listInsightVariables(api: PostHogApi): Promise<InsightVariable[]> {
    return all<InsightVariable>(api, 'insight_variables/')
}

export function createInsightVariable(
    api: PostHogApi,
    variable: { code_name: string; type: string; default_value?: unknown; is_multi?: boolean }
): Promise<InsightVariable> {
    return api.post<InsightVariable>('insight_variables/', { name: variable.code_name, ...variable })
}

export function createEndpoint(api: PostHogApi, body: Record<string, unknown>): Promise<Endpoint> {
    return api.post<Endpoint>('endpoints/', body)
}

export function updateEndpoint(api: PostHogApi, name: string, body: Record<string, unknown>): Promise<Endpoint> {
    return api.patch<Endpoint>(`endpoints/${encodeURIComponent(name)}/`, body)
}
