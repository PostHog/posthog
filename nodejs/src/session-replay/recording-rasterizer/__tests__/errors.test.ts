import { RasterizationError, asRasterizationError } from '~/session-replay/recording-rasterizer/errors'

describe('RasterizationError', () => {
    it('sets name, message, retryable, and code', () => {
        const err = new RasterizationError('something broke', true, 'TIMEOUT')
        expect(err.name).toBe('RasterizationError')
        expect(err.message).toBe('something broke')
        expect(err.retryable).toBe(true)
        expect(err.code).toBe('TIMEOUT')
        expect(err).toBeInstanceOf(Error)
    })

    it('defaults code to UNKNOWN', () => {
        const err = new RasterizationError('oops', false)
        expect(err.code).toBe('UNKNOWN')
    })

    it('stores cause when provided', () => {
        const cause = new Error('root cause')
        const err = new RasterizationError('wrapper', true, 'BLOCK_LISTING_FAILED', cause)
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
            const err = new RasterizationError('test', true, 'INVALID_INPUT', new Error('cause'))
            const json = err.toJSON()
            expect(json).not.toHaveProperty('cause')
            expect(json).not.toHaveProperty('stack')
        })
    })

    describe('asRasterizationError', () => {
        it('returns a RasterizationError unchanged', () => {
            const err = new RasterizationError('boom', false, 'NO_SNAPSHOTS')
            expect(asRasterizationError(err)).toBe(err)
        })

        // One case per way puppeteer words a dead target, because that is what varies. The CDP
        // method name in the message does not: the classifier never reads it, so a case per method
        // would be the same assertion three times.
        it.each([
            ['bare rejection from the in-flight callback', 'Target closed', 'Error'],
            [
                'CDP session already closed',
                'Protocol error (Page.captureScreenshot): Session closed. Most likely the page has been closed.',
                'Error',
            ],
            ['a wording only the error name catches', 'Page closed!', 'TargetCloseError'],
        ])('classifies %s as a retryable TARGET_CLOSED', (_label, message, name) => {
            const raw = new Error(message)
            raw.name = name
            const classified = asRasterizationError(raw)
            expect(classified).toMatchObject({
                code: 'TARGET_CLOSED',
                retryable: true,
                message: 'chrome target closed mid-render',
            })
            expect(classified?.cause).toBe(raw)
        })

        it('returns null for an unrelated error', () => {
            expect(asRasterizationError(new Error('S3 access denied'))).toBeNull()
        })
    })
})
