import { ApiError, NetworkError } from 'lib/api'

import { evaluationErrorMessage, isRequestRejection } from './apiErrors'

describe('evaluation API errors', () => {
    it.each<[string, unknown, boolean]>([
        ['treats a validation rejection as answered', new ApiError('Non-OK response', 400, undefined, {}), true],
        ['treats an access refusal as answered', new ApiError('Non-OK response', 403, undefined, {}), true],
        ['leaves a server fault reportable', new ApiError('Non-OK response', 500, undefined, {}), false],
        ['leaves a request the browser never sent reportable', new NetworkError('network'), false],
        ['leaves a plain Error reportable', new Error('Something broke'), false],
    ])('%s', (_, error, expected) => {
        expect(isRequestRejection(error)).toBe(expected)
    })

    it.each<[string, unknown, string]>([
        [
            'extracts a DRF field-level validation error',
            new ApiError('Non-OK response', 400, undefined, {
                enabled: ['Add a provider API key to enable this evaluation.'],
            }),
            'Add a provider API key to enable this evaluation.',
        ],
        [
            'extracts a nested field error from a model_configuration-style payload',
            new ApiError('Non-OK response', 400, undefined, {
                model_configuration: { provider_key_id: 'Provider key not found' },
            }),
            'Provider key not found',
        ],
        [
            'prefers detail over other keys on APIException payloads',
            new ApiError('Non-OK response', 400, undefined, {
                type: 'validation_error',
                code: 'invalid',
                detail: 'The request body is malformed.',
            }),
            'The request body is malformed.',
        ],
        [
            'returns detail when that is all the response carries',
            new ApiError('Something', 403, undefined, { detail: 'You do not have access' }),
            'You do not have access',
        ],
        [
            'falls back to the supplied default when nothing useful is available',
            new ApiError('Non-OK response [PATCH /api/...]', 500, undefined, null),
            'fallback copy',
        ],
        ['unwraps a plain Error', new Error('Network down'), 'Network down'],
    ])('%s', (_, error, expected) => {
        expect(evaluationErrorMessage(error, 'fallback copy')).toBe(expected)
    })
})
