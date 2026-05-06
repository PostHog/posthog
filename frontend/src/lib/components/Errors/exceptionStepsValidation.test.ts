import { getExceptionStepMalformedReason, getExceptionStepsMalformedReason } from './exceptionStepsValidation'

describe('exceptionStepsValidation', () => {
    describe('getExceptionStepMalformedReason', () => {
        it.each([
            {
                name: 'returns null for a valid step',
                step: { $message: 'Button clicked', $timestamp: '2024-07-09T12:00:02.500Z' },
                expected: null,
            },
            {
                name: 'fails when step is not an object',
                step: 'oops',
                expected: 'not an object',
            },
            {
                name: 'fails when message is missing',
                step: { $timestamp: '2024-07-09T12:00:02.500Z' },
                expected: 'missing $message',
            },
            {
                name: 'fails when timestamp is invalid',
                step: { $message: 'Button clicked', $timestamp: 'not-a-timestamp' },
                expected: 'missing $timestamp',
            },
            {
                name: 'fails when both message and timestamp are invalid',
                step: { $message: '   ', $timestamp: null },
                expected: 'missing $message, $timestamp',
            },
        ])('$name', ({ step, expected }) => {
            expect(getExceptionStepMalformedReason(step)).toBe(expected)
        })
    })

    describe('getExceptionStepsMalformedReason', () => {
        it.each([
            {
                name: 'returns null when steps are missing',
                rawSteps: undefined,
                expected: null,
            },
            {
                name: 'fails when steps are not an array',
                rawSteps: { step: 1 },
                expected: 'exception steps must be an array',
            },
            {
                name: 'returns the indexed malformed reason',
                rawSteps: [{ $message: 'valid', $timestamp: '2024-07-09T12:00:02.500Z' }, 'oops'],
                expected: 'step 1: not an object',
            },
            {
                name: 'returns all malformed reasons',
                rawSteps: [{}, { $message: 'valid' }],
                expected: 'step 0: missing $message, $timestamp, step 1: missing $timestamp',
            },
        ])('$name', ({ rawSteps, expected }) => {
            expect(getExceptionStepsMalformedReason(rawSteps)).toBe(expected)
        })
    })
})
