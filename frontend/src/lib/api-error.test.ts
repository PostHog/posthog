import { ENDPOINT_NOT_FOUND_DETAIL, isEndpointNotFoundError } from 'lib/api-error'

describe('isEndpointNotFoundError', () => {
    test.each([
        ['catch-all 404 from an unrouted path', { status: 404, detail: ENDPOINT_NOT_FOUND_DETAIL }, true],
        ['genuine resource 404 stays reportable', { status: 404, detail: 'Not found.' }, false],
        ['404 without a detail stays reportable', { status: 404, detail: null }, false],
        ['same detail on a non-404 status', { status: 400, detail: ENDPOINT_NOT_FOUND_DETAIL }, false],
        ['unrelated server error', { status: 500, detail: 'Internal server error' }, false],
        ['nullish error', null, false],
    ])('%s', (_name, error, expected) => {
        expect(isEndpointNotFoundError(error)).toBe(expected)
    })
})
