import { RasterizationError, isRetryableStorageError } from '~/session-replay/recording-rasterizer/errors'

describe('RasterizationError', () => {
    it('sets name, message, retryable, and code', () => {
        const err = new RasterizationError('something broke', true, 'PLAYBACK_ERROR')
        expect(err.name).toBe('RasterizationError')
        expect(err.message).toBe('something broke')
        expect(err.retryable).toBe(true)
        expect(err.code).toBe('PLAYBACK_ERROR')
        expect(err).toBeInstanceOf(Error)
    })

    it('defaults code to UNKNOWN', () => {
        const err = new RasterizationError('oops', false)
        expect(err.code).toBe('UNKNOWN')
    })

    it('stores cause when provided', () => {
        const cause = new Error('root cause')
        const err = new RasterizationError('wrapper', true, 'TEST', cause)
        expect(err.cause).toBe(cause)
    })

    it('has no cause when not provided', () => {
        const err = new RasterizationError('no cause', false)
        expect(err.cause).toBeUndefined()
    })

    describe('toJSON', () => {
        it('returns structured object with name, message, retryable, code', () => {
            const err = new RasterizationError('test error', false, 'NO_SNAPSHOTS')
            expect(err.toJSON()).toEqual({
                name: 'RasterizationError',
                message: 'test error',
                retryable: false,
                code: 'NO_SNAPSHOTS',
            })
        })

        it('does not include cause or stack in JSON', () => {
            const err = new RasterizationError('test', true, 'ERR', new Error('cause'))
            const json = err.toJSON()
            expect(json).not.toHaveProperty('cause')
            expect(json).not.toHaveProperty('stack')
        })
    })
})

describe('isRetryableStorageError', () => {
    it.each([
        ['Smithy deserialization of a non-XML body', Object.assign(new Error("char 'E' is not expected.:1:1"), {})],
        ['explicit Deserialization error text', new Error('Deserialization error: something')],
        ['AWS SDK $retryable tag', Object.assign(new Error('throttled'), { $retryable: { throttling: true } })],
        ['5xx via $metadata', Object.assign(new Error('boom'), { $metadata: { httpStatusCode: 503 } })],
        ['5xx via $response', Object.assign(new Error('boom'), { $response: { statusCode: 500 } })],
        ['transient socket reset', Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' })],
        ['SDK TimeoutError', Object.assign(new Error('timed out'), { name: 'TimeoutError' })],
    ])('treats %s as retryable', (_label, err) => {
        expect(isRetryableStorageError(err)).toBe(true)
    })

    it.each([
        ['a 4xx client error', Object.assign(new Error('AccessDenied'), { $metadata: { httpStatusCode: 403 } })],
        ['a plain unrelated error', new Error('unexpected failure')],
        ['a non-Error value', 'string error'],
    ])('does not treat %s as retryable', (_label, err) => {
        expect(isRetryableStorageError(err)).toBe(false)
    })
})
