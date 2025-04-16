import { PostHog } from 'posthog-node'
import { SeverityLevel } from 'posthog-node/src/extensions/error-tracking/types'

import { defaultConfig } from '../config/config'
import { Team } from '../types'

const posthog = defaultConfig.POSTHOG_API_KEY
    ? new PostHog(defaultConfig.POSTHOG_API_KEY, {
          host: defaultConfig.POSTHOG_HOST_URL,
          enableExceptionAutocapture: false, // TODO - disabled while data volume is a problem, PS seems /extremely/ chatty exceptions wise
      })
    : null

if (process.env.NODE_ENV === 'test' && posthog) {
    void posthog.disable()
}

export function captureTeamEvent(
    team: Team,
    event: string,
    properties: Record<string, any> = {},
    distinctId: string | null = null
): void {
    if (posthog) {
        posthog.capture({
            distinctId: distinctId ?? team.uuid,
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
}

export function shutdown(): Promise<void> | null {
    return posthog ? posthog.shutdown() : null
}

export function flush(): void {
    if (posthog) {
        void posthog.flush().catch(() => null)
    }
}

// We use sentry-style hints rather than our flat property list all over the place,
// so define a type for them that we can flatten internally
type Primitive = number | string | boolean | bigint | symbol | null | undefined
interface ExceptionHint {
    level: SeverityLevel
    tags: Record<string, Primitive>
    extra: Record<string, any>
}

export function captureException(exception: any, hint?: Partial<ExceptionHint>): void {
    if (posthog) {
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
}
