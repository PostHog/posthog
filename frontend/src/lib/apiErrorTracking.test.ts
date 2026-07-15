import { ApiError } from './api-error'
import {
    apiErrorFingerprint,
    beforeSendExceptionFilter,
    dropExpectedAuthExceptions,
    fingerprintApiErrorExceptions,
    NOT_AUTHENTICATED_DETAIL,
    normalizeEndpointForFingerprint,
    registerExceptionFilter,
} from './apiErrorTracking'

describe('apiErrorTracking', () => {
    describe('dropExpectedAuthExceptions', () => {
        it('drops $exception events carrying the expected no-credentials 401', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'ApiError', value: NOT_AUTHENTICATED_DETAIL }] },
            }
            expect(dropExpectedAuthExceptions(event)).toBeNull()
        })

        it('keeps other API errors, including genuine login failures', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'ApiError', value: 'Invalid email or password.' }] },
            }
            expect(dropExpectedAuthExceptions(event)).toBe(event)
        })

        it('passes through non-exception events and null (before_send contract)', () => {
            const pageview = { event: '$pageview', properties: {} }
            expect(dropExpectedAuthExceptions(pageview)).toBe(pageview)
            expect(dropExpectedAuthExceptions(null)).toBeNull()
        })
    })

    describe('normalizeEndpointForFingerprint', () => {
        // Without normalization each resource id would fingerprint separately, exploding one
        // logical failure into thousands of issues — the cardinality blowup this guards against.
        it.each([
            ['GET /api/projects/123/insights/', 'GET /api/projects/:id/insights/'],
            [
                'DELETE /api/projects/1/dashboards/019e649e-fe56-72cb-a765-5fd7789f2255',
                'DELETE /api/projects/:id/dashboards/:uuid',
            ],
            ['GET /api/projects/1/insights/aBc123XyZ456QrS0?refresh=true', 'GET /api/projects/:id/insights/:id'],
        ])('normalizes %s', (raw, expected) => {
            expect(normalizeEndpointForFingerprint(raw)).toBe(expected)
        })

        it('returns empty string for a missing endpoint', () => {
            expect(normalizeEndpointForFingerprint(null)).toBe('')
        })
    })

    describe('apiErrorFingerprint', () => {
        it('fingerprints by status and normalized endpoint', () => {
            const error = new ApiError('Forbidden', 403, undefined, undefined, 'GET /api/projects/2/insights/42')
            expect(apiErrorFingerprint(error)).toBe('API 403 GET /api/projects/:id/insights/:id')
        })

        it('falls back to "error" when there is no status (network failure)', () => {
            const error = new ApiError(
                'Failed to fetch',
                undefined,
                undefined,
                undefined,
                'POST /api/projects/2/query/'
            )
            expect(apiErrorFingerprint(error)).toBe('API error POST /api/projects/:id/query/')
        })
    })

    describe('fingerprintApiErrorExceptions', () => {
        type Event = { event: string; properties: Record<string, any> }

        it('assigns a message-based fingerprint to unfingerprinted ApiErrors', () => {
            const event: Event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'ApiError', value: 'Not found.' }] },
            }
            expect(fingerprintApiErrorExceptions(event).properties.$exception_fingerprint).toBe('ApiError: Not found.')
        })

        it('never overrides a fingerprint set at capture time', () => {
            const event: Event = {
                event: '$exception',
                properties: {
                    $exception_fingerprint: 'API 403 GET /api/projects/:id/insights/:id',
                    $exception_list: [{ type: 'ApiError', value: 'Forbidden' }],
                },
            }
            expect(fingerprintApiErrorExceptions(event).properties.$exception_fingerprint).toBe(
                'API 403 GET /api/projects/:id/insights/:id'
            )
        })

        it('leaves non-ApiError exceptions ungrouped', () => {
            const event: Event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
            }
            expect(fingerprintApiErrorExceptions(event).properties.$exception_fingerprint).toBeUndefined()
        })
    })

    describe('beforeSendExceptionFilter', () => {
        it('applies base filters: drops expected 401s and fingerprints other ApiErrors', () => {
            expect(
                beforeSendExceptionFilter({
                    event: '$exception',
                    properties: { $exception_list: [{ type: 'ApiError', value: NOT_AUTHENTICATED_DETAIL }] },
                } as any)
            ).toBeNull()

            const kept = beforeSendExceptionFilter({
                event: '$exception',
                properties: { $exception_list: [{ type: 'ApiError', value: 'Server error' }] },
            } as any)
            expect((kept as any).properties.$exception_fingerprint).toBe('ApiError: Server error')
        })

        it('composes registered dynamic filters and stops running them once registered', () => {
            const event = {
                event: '$exception',
                properties: { $exception_list: [{ type: 'CustomError', value: 'boom' }] },
            }
            const unregister = registerExceptionFilter((e) => (e?.event === '$exception' ? null : e))
            expect(beforeSendExceptionFilter(event as any)).toBeNull()

            unregister()
            expect(beforeSendExceptionFilter(event as any)).toBe(event)
        })
    })
})
