import { extractValidationErrorCode } from '~/queries/nodes/InsightViz/utils'

describe('extractValidationErrorCode', () => {
    test.each([
        ['code set directly on the error (async polling shape)', { status: 400, code: 'some_code' }, 'some_code'],
        ['code in the response body (sync DRF shape)', { status: 512, data: { code: 'some_code' } }, 'some_code'],
        [
            'memory-limit error (status 513)',
            { status: 513, code: 'clickhouse_memory_limit_exceeded' },
            'clickhouse_memory_limit_exceeded',
        ],
        ['non-validation status', { status: 500, code: 'some_code' }, null],
        ['no error', null, null],
    ])('%s', (_name, error, expected) => {
        expect(extractValidationErrorCode(error)).toBe(expected)
    })
})
