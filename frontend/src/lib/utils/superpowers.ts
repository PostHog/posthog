import { PreflightStatus, UserType } from '~/types'

/**
 * Whether internal diagnostics (query IDs, ClickHouse engine stats, the Kea devtools panel) may be shown.
 * These read as unfinished UI to a customer, but staff and local development need them.
 *
 * Matches `superpowersLogic.superpowersEnabled`, which keeps its own copy: making that selector call this
 * narrows its return type and rewrites the generated types of every logic that connects to it.
 */
export function hasSuperpowers(user: UserType | null, preflight: PreflightStatus | null): boolean {
    return !!(user?.is_staff || preflight?.is_debug || preflight?.instance_preferences?.debug_queries)
}
