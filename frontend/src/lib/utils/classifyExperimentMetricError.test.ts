import { QUERY_TIMEOUT_ERROR_MESSAGE } from '~/queries/query'

import { classifyExperimentMetricError, ExperimentMetricErrorType } from './eventUsageLogic'

describe('classifyExperimentMetricError', () => {
    const cases: [
        string,
        { errorCode: string | null; statusCode: number | null; errorMessage: string | null },
        ExperimentMetricErrorType,
    ][] = [
        [
            'trusts a taxonomy value forwarded by the backend over the status code',
            { errorCode: 'out_of_memory', statusCode: 400, errorMessage: null },
            'out_of_memory',
        ],
        [
            'maps the legacy memory_limit_exceeded code onto the taxonomy',
            { errorCode: 'memory_limit_exceeded', statusCode: 400, errorMessage: null },
            'out_of_memory',
        ],
        [
            'classifies the client-side poll timeout, which the backend never sees',
            { errorCode: null, statusCode: null, errorMessage: QUERY_TIMEOUT_ERROR_MESSAGE },
            'timeout',
        ],
        ['classifies a 429 as rate limited', { errorCode: null, statusCode: 429, errorMessage: null }, 'rate_limited'],
        [
            'classifies a 400 without a code as a validation error',
            { errorCode: null, statusCode: 400, errorMessage: null },
            'validation_error',
        ],
        [
            'falls back to server_error for a 500',
            { errorCode: null, statusCode: 500, errorMessage: 'boom' },
            'server_error',
        ],
        [
            'falls back to server_error for an unrecognized code',
            { errorCode: 'something_new', statusCode: null, errorMessage: null },
            'server_error',
        ],
    ]

    it.each(cases)('%s', (_name, input, expected) => {
        expect(classifyExperimentMetricError(input)).toBe(expected)
    })
})
