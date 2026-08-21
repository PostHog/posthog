import { apiFailureCaptureProperties, ApiError, isTransientServerError, shouldReportApiFailure } from './api-error'

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
            // Only the listed codes are excused: a 403 the app does not recover from is still a
            // signal, and read-only mode is dropped later by its own `before_send` filter.
            ['a 403 with no code', { status: 403 }, true],
            ['a read-only-mode 403', { status: 403, code: 'read_only_blocked' }, true],
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

        // A self-hosted or dev instance's own backend threw the untyped 500, so it is not our defect.
        // The generic DRF detail is the untyped marker alongside the `error` code.
        it.each([
            ['on cloud', true, true],
            ['on a self-hosted host', false, false],
            ['when cloud is unknown', undefined, true],
        ])('reports an untyped 500 %s', (_, isCloud, expected) => {
            expect(
                shouldReportApiFailure({ status: 500, code: 'error', detail: 'A server error occurred.' }, { isCloud })
            ).toBe(expected)
        })

        // A typed 500 carries a real backend code, so it stays reportable even off cloud.
        it('reports a typed 500 off cloud', () => {
            expect(shouldReportApiFailure({ status: 500, code: 'clickhouse_error' }, { isCloud: false })).toBe(true)
        })

        // A deliberate `APIException` with a custom message reuses DRF's `error` code but keeps its
        // own detail. Matching the code alone would drop these off cloud; the specific message must
        // keep it reportable.
        it('reports a 500 that reuses the error code but names a specific failure off cloud', () => {
            expect(
                shouldReportApiFailure(
                    { status: 500, code: 'error', detail: 'ClickHouse error while executing query.' },
                    { isCloud: false }
                )
            ).toBe(true)
        })
    })

    describe('apiFailureCaptureProperties', () => {
        it('names the failed endpoint and status', () => {
            const error = new ApiError('boom', 500)
            error.endpoint = 'GET /api/projects/1/insights'

            expect(apiFailureCaptureProperties(error)).toEqual({
                api_endpoint: 'GET /api/projects/1/insights',
                api_status: 500,
            })
        })

        it('returns nothing for a non-ApiError', () => {
            expect(apiFailureCaptureProperties(new Error('boom'))).toEqual({})
        })
    })
})
