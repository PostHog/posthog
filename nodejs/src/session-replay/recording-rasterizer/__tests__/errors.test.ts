import { RasterizationError } from '../errors'

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
