import { ApiError } from 'lib/api-error'

import { shouldReportLoaderFailure } from './initKea'

describe('shouldReportLoaderFailure', () => {
    it.each([
        // The recording player shows its own "not found" state for a deleted or expired recording,
        // so the expected 404 is noise in error tracking.
        ['an allow-listed 404', new ApiError('Recording not found', 404), 'loadRecordingMeta', false],
        // Only the 404 is excused; a real failure on the same action still reports.
        ['an allow-listed 500', new ApiError('boom', 500), 'loadRecordingMeta', true],
        ['an allow-listed network error', new ApiError('offline'), 'loadRecordingMeta', true],
        // A 404 on an action with no self-handled UI is still a signal.
        ['a 404 on an action not in the allow list', new ApiError('gone', 404), 'loadDashboard', true],
        // Only an ApiError carries a trusted status; a bare object is not excused.
        ['a plain object shaped like a 404', { status: 404 }, 'loadRecordingMeta', true],
    ])('decides whether to report %s', (_, error, actionKey, expected) => {
        expect(shouldReportLoaderFailure(error, actionKey)).toBe(expected)
    })
})
