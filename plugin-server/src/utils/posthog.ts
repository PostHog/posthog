import { PostHog } from 'posthog-node'

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

const captureTeamEvent = (
    team: Team,
    event: string,
    properties: Record<string, any> = {},
    distinctId: string | null = null
): void => {
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

function shutdown(): Promise<void> | null {
    return posthog ? posthog.shutdown() : null
}

function flush(): void {
    if (posthog) {
        void posthog.flush().catch(() => null)
    }
}

function captureException(exception: unknown, additionalProperties?: Record<string | number, any>): void {
    if (posthog) {
        posthog.captureException(exception, undefined, additionalProperties)
    }
}

export default {
    flush,
    shutdown,
    captureException,
    captureTeamEvent,
}
