import { QUERY_TIMEOUT_ERROR_MESSAGE } from '~/queries/query'

import {
    classifyExperimentMetricError,
    experimentMetricErrorMessage,
    ExperimentMetricErrorType,
} from './eventUsageLogic'

describe('experiment metric error telemetry', () => {
    const classifierCases: [
        string,
        {
            errorCode: string | null
            statusCode: number | null
            errorMessage: string | null
            hasDiagnostics?: boolean
        },
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
            'keeps the no-results state out of validation_error when flagged by code',
            { errorCode: 'no-results', statusCode: 400, errorMessage: null },
            'insufficient_data',
        ],
        [
            'keeps the no-results state out of validation_error when it only carries diagnostics',
            { errorCode: 'invalid', statusCode: 400, errorMessage: null, hasDiagnostics: true },
            'insufficient_data',
        ],
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

    it.each(classifierCases)('classify: %s', (_name, input, expected) => {
        expect(classifyExperimentMetricError(input)).toBe(expected)
    })

    const messageCases: [string, unknown, string | null][] = [
        ['passes a plain message through', 'Query failed', 'Query failed'],
        [
            'names the reasons a diagnostics blob has set instead of dumping the JSON',
            { 'no-exposures': true, 'no-control-variant': false, 'no-test-variant': true },
            'no-exposures, no-test-variant',
        ],
        ['returns null when a diagnostics blob has no reason set', { 'no-exposures': false }, null],
        ['returns null when there is no detail at all', undefined, null],
    ]

    it.each(messageCases)('message: %s', (_name, errorDetail, expected) => {
        expect(experimentMetricErrorMessage(errorDetail)).toBe(expected)
    })
})
