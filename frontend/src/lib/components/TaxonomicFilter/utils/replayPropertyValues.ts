/**
 * Value suggestions for replay property filters come from replay's own recording data
 * (`all_urls` for `visited_page`), which is what those filters match against. Sourcing them
 * from `$pageview` events instead leaves the picker empty for any project that doesn't send
 * `$pageview` — mobile, SPA, or a custom pageview event name.
 */
export function replayPropertyValuesEndpoint(teamId: number, key: string): string {
    return `api/projects/${teamId}/session_recordings/property_values/?key=${encodeURIComponent(key)}`
}
