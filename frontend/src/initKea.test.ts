import { ResponseBodyReadError } from 'lib/api-error'

import { isReportableLoaderFailure } from './initKea'

describe('isReportableLoaderFailure', () => {
    it.each([
        ['a plain error', new Error('boom'), true],
        ['a 500 ApiError', { status: 500 }, true],
        ['a transient gateway status', { status: 502 }, false],
        [
            'a ResponseBodyReadError',
            new ResponseBodyReadError('Failed to read response body [GET /x] (status 200)'),
            false,
        ],
    ])('classifies %s', (_desc, error, expected) => {
        expect(isReportableLoaderFailure(error)).toBe(expected)
    })
})
