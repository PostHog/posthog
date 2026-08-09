import { CyclotronJobInputSchemaType, CyclotronJobTestInvocationResult, LogEntry } from '~/types'

import {
    getApiErrorMessage,
    getHogFunctionDeliveryType,
    getTestInvocationFailureMessage,
    redactSecretHogFunctionInputs,
} from './hog-function-utils'

function errorLog(message: string): LogEntry {
    return {
        log_source_id: 'src',
        instance_id: 'inst',
        timestamp: '2026-08-09T00:00:00Z',
        level: 'ERROR',
        message,
    }
}

function testResult(overrides: Partial<CyclotronJobTestInvocationResult>): CyclotronJobTestInvocationResult {
    return { status: 'error', logs: [], result: null, ...overrides }
}

// The diff-builder test covers schema-marked secrets end to end; this covers the entry-marked branch
// (a saved secret carries `secret: true` on the input entry itself, with no schema flag needed).
describe('redactSecretHogFunctionInputs', () => {
    it('redacts entry-marked secrets and leaves plain inputs untouched', () => {
        const redacted = redactSecretHogFunctionInputs(
            {
                token: { value: 'tok-cleartext', secret: true },
                url: { value: 'https://example.com' },
            },
            [] as CyclotronJobInputSchemaType[]
        )
        expect(redacted.token.value).toBe('[secret]')
        expect(redacted.url.value).toBe('https://example.com')
    })
})

describe('getHogFunctionDeliveryType', () => {
    it.each([
        ['batch-export-9', 'batch'],
        ['batch-export-AwsS3', 'batch'],
        ['plugin-7', 'realtime'],
        ['abc123', 'realtime'],
        ['template-slack', 'realtime'],
    ])('classifies %s as %s', (id, expected) => {
        expect(getHogFunctionDeliveryType({ id })).toBe(expected)
    })
})

describe('getTestInvocationFailureMessage', () => {
    it('maps a Slack error code in the log line to an actionable next step', () => {
        const message = getTestInvocationFailureMessage(
            testResult({
                logs: [errorLog("Failed to post message to Slack: 200: {'ok': false, 'error': 'not_in_channel'}")],
            })
        )
        expect(message).toBe(
            'The PostHog bot is not in this channel. Invite the bot to the channel, then send the test again.'
        )
    })

    it('returns the first error line when no Slack code is recognized', () => {
        const message = getTestInvocationFailureMessage(
            testResult({ errors: ['Function exceeded the timeout'], logs: [errorLog('some noisy log')] })
        )
        expect(message).toBe('Function exceeded the timeout')
    })

    it.each([['success'], ['skipped']] as const)('returns null for a %s result', (status) => {
        expect(getTestInvocationFailureMessage(testResult({ status }))).toBeNull()
    })

    it('returns null when there is no result', () => {
        expect(getTestInvocationFailureMessage(null)).toBeNull()
    })
})

describe('getApiErrorMessage', () => {
    it('reads a field validation dict when detail is absent', () => {
        // A DRF validation response is a per-field dict with no `detail` key, so reading `detail`
        // alone collapses every field error to one generic string.
        expect(getApiErrorMessage({ data: { channel: ['This field is required.'] } })).toBe('This field is required.')
    })

    it('prefers detail when present', () => {
        expect(getApiErrorMessage({ detail: 'Not found', data: { channel: ['ignored'] } })).toBe('Not found')
    })

    it('returns null when no message can be read', () => {
        expect(getApiErrorMessage({})).toBeNull()
    })
})
