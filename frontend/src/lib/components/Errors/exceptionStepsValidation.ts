import { dayjs } from 'lib/dayjs'

export type RawExceptionStep = Record<string, unknown> & {
    type?: unknown
    message?: unknown
    level?: unknown
    timestamp?: unknown
}

export function getExceptionStepMalformedReason(step: unknown): string | null {
    if (!step || typeof step !== 'object' || Array.isArray(step)) {
        return 'not an object'
    }

    const rawStep = step as RawExceptionStep
    const message = typeof rawStep.message === 'string' && rawStep.message.trim() ? rawStep.message : null
    const timestamp = rawStep.timestamp
    const hasValidTimestamp =
        (typeof timestamp === 'string' || typeof timestamp === 'number') && dayjs.utc(timestamp).isValid()

    const missing = [!message && 'message', !hasValidTimestamp && 'timestamp'].filter(Boolean)
    if (missing.length > 0) {
        return `missing ${missing.join(', ')}`
    }

    return null
}

export function getExceptionStepsMalformedReason(rawSteps: unknown): string | null {
    if (rawSteps == null) {
        return null
    }

    if (!Array.isArray(rawSteps)) {
        return 'exception steps must be an array'
    }

    const malformedReasons = rawSteps
        .map((step, index) => {
            const reason = getExceptionStepMalformedReason(step)
            return reason ? `step ${index}: ${reason}` : null
        })
        .filter((reason): reason is string => Boolean(reason))

    return malformedReasons.length > 0 ? malformedReasons.join(', ') : null
}
