// Slack `chat.postMessage` returns HTTP 200 with `{ "ok": false, "error": "<code>" }`
// for most failures, so the Slack Hog template (posthog/cdp/templates/slack/template_slack.py)
// raises `Error('Failed to post message to Slack: <status>: <body>')` rather than letting the
// HTTP-level 429/5xx retry logic see a non-2xx status. This module classifies that thrown
// message so the HogFlow executor can react: permanently disable the flow for user-config
// errors (mirrors the subscriptions path — see ee/tasks/subscriptions/auto_disable.py) and
// back off for transient errors instead of re-firing on every triggering event.

// Slack error codes that will not self-heal without user action (re-invite the bot, reconnect
// the workspace, unarchive the channel). Kept in sync with SLACK_USER_CONFIG_ERRORS in
// ee/tasks/subscriptions/__init__.py.
export const SLACK_USER_CONFIG_ERRORS = new Set<string>([
    'not_in_channel',
    'channel_not_found',
    'account_inactive',
    'is_archived',
    'invalid_auth',
    'token_revoked',
    'restricted_action',
    'org_login_required',
])

// Transient Slack errors that are expected to recover on their own — retry with backoff.
export const SLACK_TRANSIENT_ERRORS = new Set<string>(['ratelimited', 'rate_limited'])

// The literal prefix the Slack Hog template uses when it throws. Matching on it keeps this
// classification scoped to genuine Slack-post failures rather than arbitrary flow errors.
const SLACK_FAILURE_SIGNATURE = 'Failed to post message to Slack'

// The thrown message embeds the parsed response body, which the Hog VM stringifies as a dict
// (`{'ok': false, 'error': 'not_in_channel'}`). If the body failed to parse as JSON it stays a
// raw string with double quotes. Match either quote style.
const SLACK_ERROR_CODE_REGEX = /['"]error['"]\s*:\s*['"]([a-z_]+)['"]/

export type SlackErrorClassification = {
    code: string
    kind: 'terminal' | 'transient'
}

/**
 * Extract and classify the Slack error code from a thrown Hog error message.
 * Returns null when the message is not a recognizable Slack-post failure, or when the error
 * code is unknown — in which case the executor keeps its existing fail-the-job behavior rather
 * than aggressively disabling a flow for an error we don't understand.
 */
export function classifySlackError(message: string | undefined | null): SlackErrorClassification | null {
    if (!message || !message.includes(SLACK_FAILURE_SIGNATURE)) {
        return null
    }

    const code = message.match(SLACK_ERROR_CODE_REGEX)?.[1]
    if (!code) {
        return null
    }

    if (SLACK_USER_CONFIG_ERRORS.has(code)) {
        return { code, kind: 'terminal' }
    }
    if (SLACK_TRANSIENT_ERRORS.has(code)) {
        return { code, kind: 'transient' }
    }
    return null
}
