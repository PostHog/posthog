/**
 * Terminal destination errors — a shared, extensible classifier for fetch responses that
 * will never succeed on retry until a human reconfigures something (a revoked token, a bot
 * removed from a channel, a deleted resource). When a CDP source (HogFunction or HogFlow)
 * hits one of these, retrying forever is pointless and actively harmful: it wastes quota and,
 * for the shared PostHog Slack app, degrades delivery for every other tenant. The watcher uses
 * this to auto-disable the offending source instead of letting it fail unchecked.
 *
 * To support a new destination, add a detector to `TERMINAL_ERROR_DETECTORS`.
 */

export type TerminalError = {
    // Stable identifier used in logs/metrics/analytics (e.g. `slack:not_in_channel`).
    reason: string
    // Actionable, user-facing explanation surfaced in the source's logs.
    message: string
}

export type FetchResponseForClassification = {
    status: number
    body: unknown
}

export type TerminalErrorDetector = (response: FetchResponseForClassification, url: string) => TerminalError | null

// Slack returns HTTP 200 with `{ ok: false, error: "<code>" }` for application-level errors.
// These codes are configuration problems that a retry can never fix on its own. Kept in sync
// with `SLACK_USER_CONFIG_ERRORS` in `ee/tasks/subscriptions/__init__.py` (the equivalent
// auto-disable path for the subscriptions product).
export const SLACK_TERMINAL_ERROR_CODES = new Set<string>([
    'not_in_channel',
    'account_inactive',
    'is_archived',
    'channel_not_found',
    'invalid_auth',
    'token_revoked',
])

const SLACK_TERMINAL_ERROR_MESSAGES: Record<string, string> = {
    not_in_channel:
        'PostHog is not a member of this Slack channel. Re-add the PostHog app to the channel, then re-enable.',
    channel_not_found: 'The configured Slack channel no longer exists. Pick a valid channel, then re-enable.',
    is_archived: 'The configured Slack channel is archived. Pick an active channel, then re-enable.',
    account_inactive:
        'The Slack workspace connection is inactive (the bot was removed or the workspace was deactivated). Reconnect Slack, then re-enable.',
    invalid_auth: 'The Slack workspace connection is no longer valid. Reconnect Slack, then re-enable.',
    token_revoked: 'The Slack workspace connection was revoked. Reconnect Slack, then re-enable.',
}

const detectSlackTerminalError: TerminalErrorDetector = (response, url) => {
    if (!url.startsWith('https://slack.com/api/')) {
        return null
    }
    const body = response.body
    if (typeof body !== 'object' || body === null) {
        return null
    }
    const { ok, error } = body as { ok?: unknown; error?: unknown }
    if (ok !== false || typeof error !== 'string' || !SLACK_TERMINAL_ERROR_CODES.has(error)) {
        return null
    }
    return {
        reason: `slack:${error}`,
        message:
            SLACK_TERMINAL_ERROR_MESSAGES[error] ??
            `Slack rejected the request with a terminal error (${error}). Reconfigure the destination, then re-enable.`,
    }
}

export const TERMINAL_ERROR_DETECTORS: TerminalErrorDetector[] = [detectSlackTerminalError]

/**
 * Inspect a completed fetch response and return a `TerminalError` if it is a non-retryable,
 * configuration-level failure, or `null` otherwise.
 */
export const detectTerminalError = (response: FetchResponseForClassification, url: string): TerminalError | null => {
    for (const detector of TERMINAL_ERROR_DETECTORS) {
        const terminalError = detector(response, url)
        if (terminalError) {
            return terminalError
        }
    }
    return null
}
