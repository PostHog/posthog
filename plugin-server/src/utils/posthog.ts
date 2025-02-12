import { captureException as captureSentryException, captureMessage as captureSentryMessage } from '@sentry/node'
import { PostHog } from 'posthog-node'
import { SeverityLevel } from 'posthog-node/src/extensions/error-tracking/types'

import { Team } from '../types'
import { UUID7 } from './utils'

export const posthog = new PostHog('sTMFPsFhdP1Ssg', {
    host: 'https://us.i.posthog.com',
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

// We use sentry-style hints rather than our flat property lisr all over the place,
// so define a type for them that we can flatten internally
export type Primitive = number | string | boolean | bigint | symbol | null | undefined
export interface ExceptionHint {
    level: SeverityLevel
    tags: Record<string, Primitive>
    extra: Record<string, any>
}

export function captureException(exception: any, hint?: Partial<ExceptionHint>, distinctId?: string): string {
    //If the passed "exception" is a string, capture it as a message, otherwise, capture it as an exception
    let sentryId: string
    if (typeof exception === 'string') {
        sentryId = captureSentryMessage(exception, hint)
    } else {
        sentryId = captureSentryException(exception, hint)
    }

    if (!distinctId) {
        // If we weren't given a distinct_id, we randomly generate one
        distinctId = new UUID7().toString()
    }

    let flattened = {}
    if (hint) {
        flattened = {
            level: hint?.level,
            ...(hint.tags || {}),
            ...(hint.extra || {}),
        }
    }
    posthog.captureException(exception, distinctId, flattened)
    return sentryId
}
