import { getExceptionStepsMalformedReason } from './exceptionStepsValidation'
import { ErrorEventProperties } from './types'

export function addExceptionStepsMalformedWarning(eventProperties: ErrorEventProperties): ErrorEventProperties {
    const malformedReason = getExceptionStepsMalformedReason(eventProperties?.$exception_steps)
    if (!malformedReason) {
        return eventProperties
    }

    const warning = `Exception steps malformed: ${malformedReason}`
    const existingWarnings = Array.isArray(eventProperties.$cymbal_errors)
        ? eventProperties.$cymbal_errors.filter((error): error is string => typeof error === 'string')
        : []

    if (existingWarnings.includes(warning)) {
        return eventProperties
    }

    return {
        ...eventProperties,
        $cymbal_errors: [...existingWarnings, warning],
    }
}
