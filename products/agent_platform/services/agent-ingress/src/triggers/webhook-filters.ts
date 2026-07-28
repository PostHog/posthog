/**
 * Deterministic webhook payload gate. A provider like GitHub delivers every
 * `pull_request` action to the hook — `opened`, `synchronize`, `labeled`, …
 * — while an agent typically wants exactly one shape (say
 * `action == 'review_requested'` AND `requested_team.slug == 'team-security'`).
 * Filtering in `agent.md` would spend a full model session per irrelevant
 * event; this gate answers before a session exists, from the trigger's
 * declared `config.filters`.
 */

import type { WebhookFilter } from '@posthog/agent-shared'

/**
 * Walk a dot-path through plain objects, resolving OWN properties only —
 * the body is attacker-supplied, so prototype members (`constructor`,
 * `toString`, …) are never treated as payload data. Any non-object hop or
 * missing key resolves to undefined.
 */
function resolvePath(body: unknown, path: string): unknown {
    let current: unknown = body
    for (const segment of path.split('.')) {
        if (current === null || typeof current !== 'object' || Array.isArray(current)) {
            return undefined
        }
        if (!Object.hasOwn(current, segment)) {
            return undefined
        }
        current = (current as Record<string, unknown>)[segment]
    }
    return current
}

/** True when EVERY filter's path strictly equals its expected value (AND).
 *  No filters declared = every payload matches (backwards compatible). */
export function payloadMatchesFilters(body: unknown, filters: readonly WebhookFilter[] | undefined): boolean {
    if (!filters || filters.length === 0) {
        return true
    }
    return filters.every((filter) => resolvePath(body, filter.path) === filter.equals)
}
