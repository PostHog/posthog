import { isTransientQueryFailure } from '~/queries/nodes/DataNode/autoRetry'
import { QUERY_TIMEOUT_ERROR_MESSAGE } from '~/queries/query'

describe('isTransientQueryFailure', () => {
    it.each([
        ['a gateway timeout', { status: 504 }, true],
        ['a bad gateway', { status: 502 }, true],
        ['an internal server error', { status: 500 }, true],
        ['a rate limit', { status: 429 }, true],
        ['a status-less network failure', { status: 0 }, true],
        ['the async poll giving up', { message: QUERY_TIMEOUT_ERROR_MESSAGE }, true],
        ['a validation error', { status: 400, type: 'validation_error' }, false],
        ['a not found', { status: 404 }, false],
        ['a forbidden', { status: 403 }, false],
        ['a query error carrying a code', { status: 500, code: 'clickhouse_memory_limit_exceeded' }, false],
        ['nothing at all', null, false],
    ])('%s', (_name, errorObject, expected) => {
        expect(isTransientQueryFailure(errorObject)).toBe(expected)
    })
})
