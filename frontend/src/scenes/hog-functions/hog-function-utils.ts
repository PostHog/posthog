import posthog from 'posthog-js'

import {
    CyclotronJobInputSchemaType,
    CyclotronJobInputType,
    CyclotronJobTestInvocationResult,
    HogFunctionTypeType,
} from '~/types'

export type HogFunctionDeliveryType = 'batch' | 'realtime'

// Batch exports vs realtime destinations share `type: 'destination'`; the only signal is the id prefix.
export function getHogFunctionDeliveryType(item: { id: string }): HogFunctionDeliveryType {
    return item.id.startsWith('batch-export-') ? 'batch' : 'realtime'
}

export function humanizeHogFunctionType(type: HogFunctionTypeType, plural: boolean = false): string {
    if (type === 'source_webhook') {
        return 'source' + (plural ? 's' : '')
    }
    if (type === 'site_app') {
        return 'Web script' + (plural ? 's' : '')
    }
    if (type === 'transformation_log') {
        return 'log transformation' + (plural ? 's' : '')
    }
    return type.replaceAll('_', ' ') + (plural ? 's' : '')
}

/** Default char cap for a config blob attached to the PostHog AI agent as context. */
export const HOG_FUNCTION_CONTEXT_MAX_CHARS = 10_000

/**
 * Caps a stringified config blob before it's registered as PostHog AI attached context, so a pathological
 * hog source or inputs payload can't bloat the agent's context window. These are keyed entity-style items
 * (not `type: 'text'`), so they're sent once per run rather than every turn; the cap is a safety ceiling.
 */
export function truncateHogFunctionContext(value: string, max: number = HOG_FUNCTION_CONTEXT_MAX_CHARS): string {
    return value.length > max ? value.slice(0, max) + '… (truncated)' : value
}

/**
 * Replaces secret input values with a placeholder before the live form config leaves the scene (agent
 * context, approval-card diffs). A saved secret comes back masked from the API, but a value the user
 * just typed sits in form state in cleartext and must never reach the LLM. An entry counts as secret
 * when the schema marks its key secret or the entry itself carries `secret: true`.
 */
export function redactSecretHogFunctionInputs(
    inputs: Record<string, CyclotronJobInputType>,
    inputsSchema: CyclotronJobInputSchemaType[]
): Record<string, CyclotronJobInputType> {
    const secretKeys = new Set(inputsSchema.filter((schema) => schema.secret).map((schema) => schema.key))
    return Object.fromEntries(
        Object.entries(inputs).map(([key, entry]) => {
            const isSecret = secretKeys.has(key) || entry?.secret === true
            return [key, isSecret && entry ? { ...entry, value: '[secret]' } : entry]
        })
    )
}

// Slack API error codes we can turn into a next step. The wording matches the copy that
// customer analytics and warehouse sources already ship for the same failures.
const SLACK_ERROR_HINTS: Record<string, string> = {
    not_in_channel: 'The PostHog bot is not in this channel. Invite the bot to the channel, then send the test again.',
    channel_not_found: 'This channel does not exist, or the PostHog bot cannot see it. Select a different channel.',
    invalid_auth: 'The Slack connection is no longer valid. Reconnect the Slack workspace, then send the test again.',
    account_inactive:
        'The Slack connection is no longer valid. Reconnect the Slack workspace, then send the test again.',
    token_revoked: 'The Slack connection is no longer valid. Reconnect the Slack workspace, then send the test again.',
    missing_scope:
        'The Slack connection is missing a permission. Reconnect the Slack workspace, then send the test again.',
}

function firstErrorLine(result: CyclotronJobTestInvocationResult): string | null {
    const fromErrors = result.errors?.find((entry) => entry?.trim())
    if (fromErrors) {
        return fromErrors.trim()
    }
    const fromLogs = result.logs.find((log) => log.level.toLowerCase() === 'error' && log.message.trim())
    return fromLogs ? fromLogs.message.trim() : null
}

/** Returns the Slack error code inside a failed test result, or null when none is present. */
export function detectSlackErrorCode(result: CyclotronJobTestInvocationResult): string | null {
    const line = firstErrorLine(result)
    if (!line) {
        return null
    }
    return Object.keys(SLACK_ERROR_HINTS).find((code) => line.includes(code)) ?? null
}

/**
 * Turns a failed hog function test result into a message the user can act on. A known Slack error
 * code maps to a fixed next step. Any other failure returns the first error line, so the real
 * reason stays visible without opening the logs. Returns null when the result did not fail.
 */
export function getTestInvocationFailureMessage(result: CyclotronJobTestInvocationResult | null): string | null {
    if (!result || result.status !== 'error') {
        return null
    }
    const code = detectSlackErrorCode(result)
    if (code) {
        return SLACK_ERROR_HINTS[code]
    }
    return firstErrorLine(result) ?? 'The test failed. Open the logs for details.'
}

function firstApiErrorString(value: unknown): string | null {
    if (typeof value === 'string') {
        return value.trim() || null
    }
    if (Array.isArray(value)) {
        for (const entry of value) {
            const found = firstApiErrorString(entry)
            if (found) {
                return found
            }
        }
        return null
    }
    if (value && typeof value === 'object') {
        for (const entry of Object.values(value)) {
            const found = firstApiErrorString(entry)
            if (found) {
                return found
            }
        }
        return null
    }
    return null
}

/**
 * Reads a message out of a thrown API error. A DRF validation error is a per-field dict with no
 * `detail` key, so `detail` alone collapses every field error to one generic string. This falls
 * back to the first string found in `data`.
 */
export function getApiErrorMessage(error: any): string | null {
    return (
        error?.detail ?? firstApiErrorString(error?.data) ?? (typeof error?.message === 'string' ? error.message : null)
    )
}

export type HogFunctionTestProduct = 'survey_notifications' | 'error_tracking_alerts'

/**
 * Records the outcome of a hog function test invocation. These tests had no analytics event, so
 * failing setups like the Slack ones above were invisible.
 */
export function captureHogFunctionTestInvocation(properties: {
    product: HogFunctionTestProduct
    destination?: string | null
    outcome: 'success' | 'error' | 'skipped' | 'exception'
    slack_error_code?: string | null
}): void {
    posthog.capture('hog function test invoked', properties)
}
