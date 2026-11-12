import { z } from 'zod'

import { ApiError, type PostHogApi } from '@/posthog/api'
import { findNamed, getPage, listTooLong, MAX_LIMIT, readAll, type Page } from '@/posthog/pagination'

import { Endpoint, InsightVariable } from './model'

// Lookups can read many pages, so they ask for the largest page PostHog sends.
const ENDPOINT_PAGES = `endpoints/?limit=${MAX_LIMIT}`

export function listEndpoints(api: PostHogApi, limit: number, offset: number): Promise<Page<Endpoint>> {
    return getPage(api, `endpoints/?limit=${limit}${offset > 0 ? `&offset=${offset}` : ''}`, Endpoint)
}

export function readAllEndpoints(api: PostHogApi): Promise<Endpoint[]> {
    return readAll(api, ENDPOINT_PAGES, Endpoint, listTooLong('endpoints', 'Pull the endpoints you need by name.'))
}

export function getEndpoint(api: PostHogApi, name: string): Promise<Endpoint> {
    return api.get(`endpoints/${encodeURIComponent(name)}/`, Endpoint)
}

// Reads the list until it has every name. In a project too large for that, it looks up each name
// it hasn't found yet, so the cost grows with the names instead of the project.
export async function findEndpoints(api: PostHogApi, names: readonly string[]): Promise<Map<string, Endpoint>> {
    const { found, complete } = await findNamed(api, ENDPOINT_PAGES, Endpoint, names, (endpoint) => endpoint.name)
    if (!complete) {
        for (const name of names.filter((name) => !found.has(name))) {
            try {
                found.set(name, await getEndpoint(api, name))
            } catch (error) {
                if (!(error instanceof ApiError && error.status === 404)) {
                    throw error
                }
            }
        }
    }
    return found
}

// PostHog can't filter variables by name or ID, so a variable lookup pages further.
const VARIABLE_MAX_PAGES = 200

// PostHog allows a variable without a code name, which no query can reference, so a lookup skips it.
const ListedVariable = InsightVariable.extend({ code_name: z.string().nullable() })

// When `complete` is false, a name missing from `found` can still be in the project. A push then
// tries to create that variable, and PostHog rejects the duplicate for that endpoint alone.
export async function findInsightVariables(
    api: PostHogApi,
    names: readonly string[]
): Promise<{ found: Map<string, InsightVariable>; complete: boolean }> {
    const { found, complete } = await findNamed(
        api,
        'insight_variables/',
        ListedVariable,
        names,
        (variable) => variable.code_name,
        VARIABLE_MAX_PAGES
    )
    return { found: new Map([...found].map(([name, variable]) => [name, { ...variable, code_name: name }])), complete }
}

export function getInsightVariable(api: PostHogApi, id: string): Promise<InsightVariable> {
    return api.get(`insight_variables/${encodeURIComponent(id)}/`, InsightVariable)
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
