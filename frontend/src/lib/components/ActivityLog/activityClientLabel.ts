/** Written by the backend from the authenticated scout run, so a caller cannot set it. */
export const SCOUT_CLIENT_PREFIX = 'scout:'

export function isScoutClient(client: string): boolean {
    return client.startsWith(SCOUT_CLIENT_PREFIX)
}

/** How a stored `client` value reads to a person. The stored value stays the filter key. */
export function activityClientLabel(client: string): string {
    if (isScoutClient(client)) {
        return `scout ${client.slice(SCOUT_CLIENT_PREFIX.length)}`
    }
    return client === 'mcp' ? 'MCP' : client
}
