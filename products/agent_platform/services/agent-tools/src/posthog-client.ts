/**
 * Thin HTTP client for the internal PostHog Django endpoints that PostHog-data
 * tools delegate to. The runner injects the base URL; tests inject a mock.
 *
 * We keep this here (in agent-tools) rather than in the runner so each tool's
 * `run()` is a clean one-call function that can be unit-tested independently.
 */

export interface PosthogInternalClient {
    runHogql(input: { team_id: number; query: string }): Promise<{ rows: Record<string, unknown>[]; columns: string[] }>
    searchPersons(input: {
        team_id: number
        query: string
        limit: number
    }): Promise<{ persons: Array<{ id: string; distinct_id: string; properties: Record<string, unknown> }> }>
}

let CLIENT: PosthogInternalClient | null = null

export function setPosthogInternalClient(client: PosthogInternalClient): void {
    CLIENT = client
}

export function getPosthogInternalClient(): PosthogInternalClient {
    if (!CLIENT) {
        throw new Error('PosthogInternalClient not configured. Call setPosthogInternalClient first.')
    }
    return CLIENT
}
