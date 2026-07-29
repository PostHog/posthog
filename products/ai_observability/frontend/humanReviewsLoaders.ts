import { isAccessDeniedError } from 'lib/api-error'

// The human-reviews sub-tabs (queues, reviews, scorers) load their
// `llm_analytics`-scoped lists on mount, before we know whether the current user
// can read them. A user without access gets a 403, which is an expected outcome
// rather than a fault, so fall back to an empty list instead of letting the 403
// propagate out of the loader and get reported to error tracking as an uncaught
// exception. Non-permission errors still throw so genuine failures surface.
export async function loadOrEmptyOnAccessDenied<T>(load: () => Promise<T>, empty: T): Promise<T> {
    try {
        return await load()
    } catch (error) {
        if (isAccessDeniedError(error as { status?: number; code?: string | null })) {
            return empty
        }
        throw error
    }
}
