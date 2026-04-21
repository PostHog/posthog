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
                name: 'converts evaluation with all fields',
                input: {
                    evaluation: {
                        id: 'eval-123',
                        name: 'Check output quality',
                        description: 'Validates LLM output',
                        evaluation_type: 'hog' as const,
                        hog_source: 'return length(output) > 0',
                    },
                },
                expected: {
                    evaluations: [
                        {
                            id: 'eval-123',
                            name: 'Check output quality',
                            description: 'Validates LLM output',
                            evaluation_type: 'hog',
                            hog_source: 'return length(output) > 0',
                            type: MaxContextType.EVALUATION,
                        },
                    ],
                },
            },
            {
                name: 'converts evaluation with minimal fields',
                input: {
                    evaluation: {
                        id: 'eval-456',
                        evaluation_type: 'llm_judge' as const,
                    },
                },
                expected: {
                    evaluations: [
                        {
                            id: 'eval-456',
                            name: undefined,
                            description: undefined,
                            evaluation_type: 'llm_judge',
                            hog_source: undefined,
                            type: MaxContextType.EVALUATION,
                        },
                    ],
                },
            },
            {
                name: 'converts both error tracking issue and evaluation',
                input: {
                    errorTrackingIssue: { id: 'issue-1', name: 'Error' },
                    evaluation: {
                        id: 'eval-1',
                        name: 'Test eval',
                        evaluation_type: 'hog' as const,
                        hog_source: 'return true',
                    },
                },
                expected: {
                    error_tracking_issues: [
                        { id: 'issue-1', name: 'Error', type: MaxContextType.ERROR_TRACKING_ISSUE },
                    ],
                    evaluations: [
                        {
                            id: 'eval-1',
                            name: 'Test eval',
                            description: undefined,
                            evaluation_type: 'hog',
                            hog_source: 'return true',
                            type: MaxContextType.EVALUATION,
                        },
                    ],
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
