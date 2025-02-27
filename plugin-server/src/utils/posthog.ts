import { captureException as captureSentryException, captureMessage as captureSentryMessage } from '@sentry/node'
import { PostHog } from 'posthog-node'
import { SeverityLevel } from 'posthog-node/src/extensions/error-tracking/types'

import { Team } from '../types'

export const posthog = new PostHog('sTMFPsFhdP1Ssg', {
    host: 'https://us.i.posthog.com',
    enableExceptionAutocapture: false, // TODO - disabled while data volume is a problem, PS seems /extremely/ chatty exceptions wise
})

if (process.env.NODE_ENV === 'test') {
    void posthog.disable()
}

export const captureTeamEvent = (team: Team, event: string, properties: Record<string, any> = {}): void => {
    posthog.capture({
        distinctId: team.uuid,
        event,
        properties: {
            team: team.uuid,
            ...properties,
        },
        groups: {
            project: team.uuid,
            organization: team.organization_id,
            instance: process.env.SITE_URL ?? 'unknown',
        },
    })
}

// We use sentry-style hints rather than our flat property list all over the place,
// so define a type for them that we can flatten internally
export type Primitive = number | string | boolean | bigint | symbol | null | undefined
export interface ExceptionHint {
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

    // TODO - this sampling is a hack while we work on our data consumption in error tracking
    if (process.env.NODE_ENV === 'production' && Math.random() < 0.1) {
        let additionalProperties = {}
        if (hint) {
            additionalProperties = {
                ...(hint.level ? { level: hint.level } : {}),
                ...(hint.tags || {}),
                ...(hint.extra || {}),
            }
        }
        posthog.captureException(exception, undefined, additionalProperties)
    }

    return sentryId
}
