import { PushFailureReason, normalizeApnsError, normalizeFcmError } from './push-notification-errors'

describe('push notification error normalization', () => {
    describe('normalizeFcmError', () => {
        it.each<[string, number | undefined, string | undefined, string | undefined, PushFailureReason, boolean]>([
            // name, httpStatus, error.status, details.errorCode, expected reason, expected unregistered
            ['unregistered token (errorCode)', 200, 'NOT_FOUND', 'UNREGISTERED', 'unregistered', true],
            ['unregistered token (404 + NOT_FOUND)', 404, 'NOT_FOUND', undefined, 'unregistered', true],
            // A bare 404 with no FCM error body (e.g. a proxy) must NOT prune the token.
            ['bare 404 without FCM error body', 404, undefined, undefined, 'unknown', false],
            ['sender id mismatch', 403, 'PERMISSION_DENIED', 'SENDER_ID_MISMATCH', 'auth_error', false],
            ['third party auth', 401, 'UNAUTHENTICATED', 'THIRD_PARTY_AUTH_ERROR', 'auth_error', false],
            ['permission denied', 403, 'PERMISSION_DENIED', undefined, 'auth_error', false],
            ['quota exceeded', 429, 'RESOURCE_EXHAUSTED', 'QUOTA_EXCEEDED', 'rate_limited', false],
            ['rate limited by status', 429, undefined, undefined, 'rate_limited', false],
            ['invalid argument', 400, 'INVALID_ARGUMENT', undefined, 'invalid_payload', false],
            ['internal error', 500, 'INTERNAL', undefined, 'provider_error', false],
            ['unavailable', 503, 'UNAVAILABLE', undefined, 'provider_error', false],
            ['unknown', 418, "I'm a teapot", undefined, 'unknown', false],
        ])('%s', (_name, status, errorStatus, errorCode, expectedReason, expectedUnregistered) => {
            const body = { error: { status: errorStatus, details: errorCode ? [{ errorCode }] : undefined } }
            const result = normalizeFcmError(status, body, null)
            expect(result.reason).toBe(expectedReason)
            expect(result.unregistered).toBe(expectedUnregistered)
            expect(result.message.length).toBeGreaterThan(0)
        })

        it('classifies a missing response (network error)', () => {
            const result = normalizeFcmError(undefined, undefined, new Error('socket hang up'))
            expect(result.reason).toBe('network_error')
            expect(result.unregistered).toBe(false)
        })

        it('surfaces the raw provider code and prefers the specific detail errorCode', () => {
            const body = { error: { status: 'INVALID_ARGUMENT', details: [{ errorCode: 'UNREGISTERED' }] } }
            const result = normalizeFcmError(400, body, null)
            // The per-message errorCode is more specific than error.status, so it wins.
            expect(result.reason).toBe('unregistered')
            expect(result.code).toBe('UNREGISTERED')
        })
    })

    describe('normalizeApnsError', () => {
        it.each<[number | undefined, string | undefined, PushFailureReason, boolean]>([
            [410, 'Unregistered', 'unregistered', true],
            [400, 'BadDeviceToken', 'invalid_token', false],
            [400, 'DeviceTokenNotForTopic', 'invalid_token', false],
            [403, 'InvalidProviderToken', 'auth_error', false],
            [403, 'ExpiredProviderToken', 'auth_error', false],
            [429, 'TooManyRequests', 'rate_limited', false],
            [413, 'PayloadTooLarge', 'invalid_payload', false],
            [500, 'InternalServerError', 'provider_error', false],
            [503, 'ServiceUnavailable', 'provider_error', false],
            [400, 'SomethingBrandNew', 'unknown', false],
        ])('status %s reason %s -> %s', (status, reason, expectedReason, expectedUnregistered) => {
            const result = normalizeApnsError(status, { reason }, null)
            expect(result.reason).toBe(expectedReason)
            expect(result.unregistered).toBe(expectedUnregistered)
            expect(result.code).toBe(reason)
            expect(result.message.length).toBeGreaterThan(0)
        })

        it('classifies a missing response (network error)', () => {
            const result = normalizeApnsError(undefined, undefined, new Error('ECONNRESET'))
            expect(result.reason).toBe('network_error')
        })
    })

    it('maps config problems to error level and transient problems to warn', () => {
        // A user must fix credentials -> error; a dead token or throttle is expected/transient -> warn.
        const apnsAuth = normalizeApnsError(403, { reason: 'InvalidProviderToken' }, null)
        expect(apnsAuth.level).toBe('error')
        // A config-error message names the provider so the user knows which credentials to check.
        expect(apnsAuth.message).toContain('APNs')
        expect(normalizeApnsError(410, { reason: 'Unregistered' }, null).level).toBe('warn')
        expect(normalizeFcmError(429, {}, null).level).toBe('warn')
        expect(normalizeFcmError(400, { error: { status: 'INVALID_ARGUMENT' } }, null).level).toBe('error')
    })
})
