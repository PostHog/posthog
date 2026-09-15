/** Client values with this prefix name the scout that made the change, resolved from its run token. */
const SCOUT_CLIENT_PREFIX = 'scout:'

const SELF_REPORTED_TOOLTIP = 'Self-reported by the API client in the x-posthog-client request header'

export interface ActivityClientDescription {
    label: string
    tooltip: string
}

/** How to name the API client, or the scout, behind one activity log row. */
export function describeActivityClient(client: string): ActivityClientDescription {
    if (client.startsWith(SCOUT_CLIENT_PREFIX)) {
        const scoutName = client.slice(SCOUT_CLIENT_PREFIX.length)
        return {
            label: `scout ${scoutName}`,
            tooltip: `Made by the ${scoutName} scout, acting as this user. PostHog read the scout name from its run token, so it is not self-reported.`,
        }
    }
    return { label: client === 'mcp' ? 'MCP' : client, tooltip: SELF_REPORTED_TOOLTIP }
}
