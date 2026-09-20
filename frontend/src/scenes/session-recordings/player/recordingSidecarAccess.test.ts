import { ApiError } from 'lib/api-error'

import {
    isRecordingSidecarAccessDenied,
    rememberRecordingSidecarAccessDenial,
    resetRecordingSidecarAccessDenials,
} from './recordingSidecarAccess'

function accessDenied(): ApiError {
    return new ApiError('You don’t have access to the project.', 403, undefined, { code: 'permission_denied' })
}

describe('recordingSidecarAccess', () => {
    beforeEach(() => {
        resetRecordingSidecarAccessDenials()
    })

    it('remembers an access denial for the project it happened in', () => {
        rememberRecordingSidecarAccessDenial('notebook-comments', 42, accessDenied())

        expect(isRecordingSidecarAccessDenied('notebook-comments', 42)).toBe(true)
        // A viewer can hold access in one project and not in the next one they switch to.
        expect(isRecordingSidecarAccessDenied('notebook-comments', 43)).toBe(false)
        // Each panel is denied on its own resource.
        expect(isRecordingSidecarAccessDenied('experiment-context', 42)).toBe(false)
    })

    it.each([
        ['a transient gateway failure', new ApiError('Bad gateway', 502)],
        ['a feature flag gate', new ApiError('Not enabled', 403, undefined, { code: 'feature_flag_required' })],
        ['a missing resource', new ApiError('Not found', 404)],
        ['something that is not an error object', 'nope'],
    ])('keeps the panel retryable after %s', (_label, error) => {
        rememberRecordingSidecarAccessDenial('experiment-context', 42, error)

        expect(isRecordingSidecarAccessDenied('experiment-context', 42)).toBe(false)
    })

    it('is not denied when the project is unknown', () => {
        rememberRecordingSidecarAccessDenial('notebook-comments', null, accessDenied())

        expect(isRecordingSidecarAccessDenied('notebook-comments', null)).toBe(false)
    })
})
