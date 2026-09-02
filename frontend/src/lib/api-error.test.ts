import { apiFailureExceptionProperties, ApiError, isTransientServerError, shouldReportApiFailure } from './api-error'

function apiErrorWithRequest(method: string, path: string, status?: number): ApiError {
    const error = new ApiError('A server error occurred.', status)
    error.method = method
    error.path = path
    return error
}

describe('api-error', () => {
    describe('ApiError.fromResponse', () => {
        it.each([
            ['error', { error: 'error message' }, 'error message'],
            ['detail', { detail: 'detail message' }, 'detail message'],
            ['message', { message: 'message value' }, 'message value'],
        ])('uses the %s field as the error message', async (_, body, expected) => {
            const response = new Response(JSON.stringify(body), { status: 400 })

            const error = await ApiError.fromResponse(response, 'fallback')

            expect(error).toMatchObject({ message: expected, status: 400, data: body })
        })

        it('stores the request method and path when given request context', async () => {
            const response = new Response(JSON.stringify({ detail: 'A server error occurred.' }), { status: 500 })

            const error = await ApiError.fromResponse(response, 'fallback', {
                method: 'GET',
                path: '/api/projects/2/insights/9Pq3xR2t',
            })

            expect(error).toMatchObject({ method: 'GET', path: '/api/projects/2/insights/9Pq3xR2t' })
        })

        it('uses the fallback for a response without a recognized message', async () => {
            const response = new Response('Bad gateway', { status: 502 })

            const error = await ApiError.fromResponse(response, 'Request failed')

            expect(error).toMatchObject({ message: 'Request failed', status: 502, data: null })
        })

        it('preserves response metadata and prioritizes error messages consistently', async () => {
            const body = {
                error: 'primary message',
                detail: 'DRF detail',
                message: 'secondary message',
                code: 'permission_denied',
            }

            const error = await ApiError.fromResponse(new Response(JSON.stringify(body), { status: 403 }))

            expect(error).toMatchObject({
                message: 'primary message',
                detail: 'DRF detail',
                code: 'permission_denied',
                status: 403,
                data: body,
            })
        })

        it('uses the default ApiError message for an empty response without a fallback', async () => {
            const error = await ApiError.fromResponse(new Response(null, { status: 404 }))

            expect(error).toMatchObject({ message: 'API request failed with status: 404', status: 404, data: null })
        })

        it('propagates an aborted response body read', async () => {
            const abortError = new DOMException('Aborted', 'AbortError')
            const response = {
                json: jest.fn().mockRejectedValue(abortError),
            } as unknown as Response

            await expect(ApiError.fromResponse(response)).rejects.toBe(abortError)
        })
    })

    describe('isTransientServerError', () => {
        it.each([
            // The empty-bodied gateway timeout that the insight-save flows must swallow rather than rethrow.
            ['a 503 with no body (detail null)', new ApiError(undefined, 503), true],
            ['a 502 bad gateway', new ApiError(undefined, 502), true],
            ['a 504 gateway timeout', new ApiError(undefined, 504), true],
            ['a 500 application error', new ApiError('boom', 500), false],
            ['a 599', new ApiError(undefined, 599), false],
            ['a 400 validation error', new ApiError('bad', 400), false],
            ['a 403', new ApiError('nope', 403), false],
            ['a 429 rate limit', new ApiError('slow down', 429), false],
            ['an ApiError with no status', new ApiError('mystery'), false],
        ])('classifies %s', (_, error, expected) => {
            expect(isTransientServerError(error)).toBe(expected)
        })

        it.each([
            ['a plain Error', new Error('network down')],
            ['null', null],
            ['a bare object shaped like an error', { status: 503 }],
        ])('does not classify %s as transient', (_, error) => {
            expect(isTransientServerError(error)).toBe(false)
        })
    })

    describe('shouldReportApiFailure', () => {
        it.each([
            // Handled by something else, so reporting them only buries real crashes.
            ['a 401 the session check logs the user out of', { status: 401 }, false],
            ['an access-denied 403', { status: 403, code: 'permission_denied' }, false],
            ['a 2FA setup gate', { status: 403, code: 'two_factor_setup_required' }, false],
            ['a 2FA verification gate', { status: 403, code: 'two_factor_verification_required' }, false],
            ['a re-auth gate', { status: 403, code: 'sensitive_action_required_reauth' }, false],
            ['an approvals 409', { status: 409, data: { change_request_id: 'abc' } }, false],
            ['a 502', { status: 502 }, false],
            ['a 503', { status: 503 }, false],
            ['a 504', { status: 504 }, false],
            // Only the listed codes are excused: a 403 the app does not recover from is still a signal.
            ['a 403 with no code', { status: 403 }, true],
            ['a 409 that is not an approvals gate', { status: 409, data: {} }, true],
            ['a 500 backend exception', { status: 500 }, true],
            ['a 400 validation error', { status: 400 }, true],
            ['a 404', { status: 404 }, true],
            // No HTTP response to excuse the failure.
            ['an error with no status', { message: 'boom' }, true],
            ['a thrown string', 'went wrong', true],
            ['null', null, true],
        ])('decides whether to report %s', (_, error, expected) => {
            expect(shouldReportApiFailure(error)).toBe(expected)
        })

        // The hand-written cases above use literals; this proves the shape `fromResponse` actually
        // builds (`code` lifted off the response body) classifies the same way.
        it('reads the code off a constructed ApiError', async () => {
            const body = { detail: "You don't have access to the project.", code: 'permission_denied' }
            const error = await ApiError.fromResponse(new Response(JSON.stringify(body), { status: 403 }))

            expect(shouldReportApiFailure(error)).toBe(false)
        })
    })

    describe('apiFailureExceptionProperties', () => {
        const fingerprint = (method: string, path: string, status?: number): string =>
            apiFailureExceptionProperties(apiErrorWithRequest(method, path, status))!.$exception_fingerprint as string

        it('gives one fingerprint per endpoint, method and status, collapsing resource ids', () => {
            // Two resources under the same endpoint share one issue.
            expect(fingerprint('GET', '/api/projects/2/insights/9Pq3xR2t', 500)).toBe(
                fingerprint('GET', '/api/projects/7/insights/aB4kZ9mn', 500)
            )
            // A different endpoint, method, or status splits it.
            expect(fingerprint('GET', '/api/projects/2/insights/9Pq3xR2t', 500)).not.toBe(
                fingerprint('GET', '/api/projects/2/dashboards/9Pq3xR2t', 500)
            )
            expect(fingerprint('GET', '/api/projects/2/insights/9Pq3xR2t', 500)).not.toBe(
                fingerprint('POST', '/api/projects/2/insights/9Pq3xR2t', 500)
            )
            expect(fingerprint('GET', '/api/projects/2/insights/9Pq3xR2t', 500)).not.toBe(
                fingerprint('GET', '/api/projects/2/insights/9Pq3xR2t', 404)
            )
        })

        it.each([
            ['a numeric id', '/api/projects/2', '/api/projects/58'],
            [
                'a uuid',
                '/api/projects/2/persons/018f2b3c-4d5e-6f70-8901-234567890abc',
                '/api/projects/2/persons/0190aabb-ccdd-7eef-8011-223344556677',
            ],
            ['a base62 short id', '/api/projects/2/insights/9Pq3xR2t', '/api/projects/2/insights/aB4kZ9mn'],
        ])('collapses %s so the endpoint keeps one fingerprint', (_, pathA, pathB) => {
            expect(fingerprint('GET', pathA, 500)).toBe(fingerprint('GET', pathB, 500))
        })

        it('reports the actual path and status as readable properties', () => {
            expect(
                apiFailureExceptionProperties(apiErrorWithRequest('GET', '/api/projects/2/insights/9Pq3xR2t', 500))
            ).toMatchObject({
                api_request_method: 'GET',
                api_request_path: '/api/projects/2/insights/9Pq3xR2t',
                api_response_status: 500,
            })
        })

        it.each([
            ['a plain Error', new Error('boom')],
            ['null', null],
            ['an ApiError with no request context', new ApiError('boom', 500)],
        ])('returns undefined for %s', (_, error) => {
            expect(apiFailureExceptionProperties(error)).toBeUndefined()
        })
    })
})
