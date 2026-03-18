import { MaxContextType } from './maxTypes'
import { MaxOpenContext, convertToMaxUIContext } from './utils'

describe('maxContextConverters', () => {
    describe('convertToMaxUIContext', () => {
        it.each([
            {
                name: 'converts error tracking issue with id only',
                input: { errorTrackingIssue: { id: 'abc-123' } },
                expected: {
                    error_tracking_issues: [
                        { id: 'abc-123', name: undefined, type: MaxContextType.ERROR_TRACKING_ISSUE },
                    ],
                },
            },
            {
                name: 'converts error tracking issue with id and name',
                input: { errorTrackingIssue: { id: 'xyz-789', name: 'TypeError: undefined' } },
                expected: {
                    error_tracking_issues: [
                        { id: 'xyz-789', name: 'TypeError: undefined', type: MaxContextType.ERROR_TRACKING_ISSUE },
                    ],
                },
            },
            {
                name: 'converts error tracking issue with null name',
                input: { errorTrackingIssue: { id: 'def-456', name: null } },
                expected: {
                    error_tracking_issues: [{ id: 'def-456', name: null, type: MaxContextType.ERROR_TRACKING_ISSUE }],
                },
            },
            {
                name: 'returns empty object for empty context',
                input: {},
                expected: {},
            },
            {
                name: 'returns empty object when errorTrackingIssue is undefined',
                input: { errorTrackingIssue: undefined } as MaxOpenContext,
                expected: {},
            },
        ])('$name', ({ input, expected }) => {
            expect(convertToMaxUIContext(input)).toEqual(expected)
        })
    })
})
