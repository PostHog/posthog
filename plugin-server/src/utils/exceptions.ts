import { captureException as captureSentryException, captureMessage as captureSentryMessage } from '@sentry/node'
import { SeverityLevel } from 'posthog-node/src/extensions/error-tracking/types'

import posthog from './posthog'

// We use sentry-style hints rather than our flat property list all over the place,
// so define a type for them that we can flatten internally
type Primitive = number | string | boolean | bigint | symbol | null | undefined
interface ExceptionHint {
    level: SeverityLevel
    tags: Record<string, Primitive>
    extra: Record<string, any>
}

export function captureException(exception: any, hint?: Partial<ExceptionHint>): string {
    //If the passed "exception" is a string, capture it as a message, otherwise, capture it as an exception
    let sentryId: string
    if (typeof exception === 'string') {
        sentryId = captureSentryMessage(exception, hint)
    } else {
        sentryId = captureSentryException(exception, hint)
    }

    let additionalProperties = {}
    if (hint) {
        additionalProperties = {
            ...(hint.level ? { level: hint.level } : {}),
            ...(hint.tags || {}),
            ...(hint.extra || {}),
        }
    }
    posthog.captureException(exception, additionalProperties)

    return sentryId
}
