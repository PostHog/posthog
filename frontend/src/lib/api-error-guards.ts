import { ApiError } from 'lib/api-error'

/**
 * The exact `detail` the backend returns (with a 404) when an environment-scoped request targets a
 * team the user can no longer reach — a deleted team, revoked access, or a `currentTeamId` left stale
 * after an org/team switch. See `posthog/api/routing.py`.
 */
export const PROJECT_NOT_FOUND_DETAIL = 'Project not found.'

/**
 * True when `error` is the backend's "current environment is gone" 404. Loaders that fire on app-shell
 * mount (e.g. dashboards, conversation history) use this to degrade to an empty result instead of letting
 * the stale-team 404 reject into React render.
 *
 * Kept in its own module (rather than on `ApiError` in `lib/api-error`) so the fix doesn't touch a file
 * that `lib/api` transitively pulls into nearly every test — which would balloon CI's changed-file test
 * selection.
 */
export function isProjectNotFoundError(error: unknown): boolean {
    return error instanceof ApiError && error.status === 404 && error.detail === PROJECT_NOT_FOUND_DETAIL
}
