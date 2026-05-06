import { addExceptionStepsMalformedWarning } from './errorDisplayWarnings'

describe('errorDisplayWarnings', () => {
    it('returns the original object when exception steps are valid', () => {
        const eventProperties = {
            $exception_steps: [{ $message: 'Button clicked', $timestamp: '2024-07-09T12:00:02.500Z' }],
        }

        const result = addExceptionStepsMalformedWarning(eventProperties as any)

        expect(result).toBe(eventProperties)
    })

    it('appends malformed-step warning to ingestion errors', () => {
        const eventProperties = {
            $exception_steps: [{}],
            $cymbal_errors: ['existing ingestion warning'],
        }

        const result = addExceptionStepsMalformedWarning(eventProperties as any)

        expect(result).not.toBe(eventProperties)
        expect(eventProperties.$cymbal_errors).toEqual(['existing ingestion warning'])
        expect(result.$cymbal_errors).toEqual([
            'existing ingestion warning',
            'Exception steps malformed: step 0: missing $message, $timestamp',
        ])
    })

    it('does not duplicate malformed-step warning if already present', () => {
        const warning = 'Exception steps malformed: step 0: missing $message, $timestamp'
        const eventProperties = {
            $exception_steps: [{}],
            $cymbal_errors: [warning],
        }

        const result = addExceptionStepsMalformedWarning(eventProperties as any)

        expect(result).toBe(eventProperties)
        expect(result.$cymbal_errors).toEqual([warning])
    })

    it('creates cymbal errors when none exist', () => {
        const eventProperties = {
            $exception_steps: 'not-an-array',
        }

        const result = addExceptionStepsMalformedWarning(eventProperties as any)

        expect(result.$cymbal_errors).toEqual(['Exception steps malformed: exception steps must be an array'])
    })
})
