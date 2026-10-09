/** The fields of a PostHog API error that the messages below read. `ApiError` has them all. */
interface ApiErrorLike {
    status?: number
    code?: string | null
    detail?: string | null
}

function asApiError(error: unknown): ApiErrorLike {
    return error && typeof error === 'object' ? (error as ApiErrorLike) : {}
}

const RUN_ERROR_MESSAGES: Record<string, string> = {
    usage_limited:
        'This project reached its usage limit, so the run did not start. Raise the limit in billing settings, then try again.',
    create_rate_limited: 'This project started too many runs in the last hour. Wait a few minutes, then try again.',
    concurrency_limited:
        'This project already has the maximum number of runs in progress. Wait for one to finish or cancel one, then try again.',
    repository_required: 'Choose a repository for the run, or set a default repository in settings.',
    run_done: 'This run is done and cannot continue. Start a new run to continue the work.',
    credential_owner_required:
        'This run uses the subscription of the person who started it, so only that person can continue it. Start a new run to use your own.',
    run_stopping: 'This run is stopping. Wait until it stops, then send your message to continue it.',
    run_not_ready: 'This run is still starting. Try again in a few seconds.',
    run_not_resumable: 'This run cannot be continued. Start a new run from the same prompt.',
    cancel_unavailable: 'This run cannot be canceled right now. Refresh the page and try again.',
}

/** The message for a failed run request: a known error code first, then the API detail, then the fallback. */
export function describeRunError(error: unknown, fallback: string): string {
    const { code, detail } = asApiError(error)
    if (code && RUN_ERROR_MESSAGES[code]) {
        return RUN_ERROR_MESSAGES[code]
    }
    return detail || fallback
}

/** The message for a failed attempt to connect a Claude subscription. */
export function describeClaudeSubscriptionError(error: unknown): string {
    const { status, detail } = asApiError(error)
    if (status === 400) {
        return detail || 'This does not look like a Claude token. Run the command again, then paste the new token.'
    }
    if (status === 404) {
        return 'Your organization cannot connect a Claude subscription yet. Ask PostHog support to turn it on.'
    }
    return detail || 'Could not connect Claude. Try again, and contact support if it keeps happening.'
}
