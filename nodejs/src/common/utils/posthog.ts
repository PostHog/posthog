import { CaptureError, PostHog } from 'posthog-node'
import { Counter } from 'prom-client'

import { Team } from '~/types'

import { defaultConfig } from '../config/config'
import { logger } from './logger'

const fs = require('fs')

const captureEventsLostCounter = new Counter({
    name: 'posthog_sdk_capture_events_lost_total',
    help: "Events this service's PostHog client could not deliver, by capture endpoint and reason.",
    labelNames: ['endpoint', 'reason'],
})

const UNDELIVERED = 'undelivered'

/**
 * The events a failed capture batch lost, by reason. A dropped event counts under the drop detail
 * capture or the client gave it. An event with no accepted result counts as `undelivered`: its
 * request failed, its retries ran out, or it was still queued at shutdown.
 */
export function countCaptureLosses(error: CaptureError): Map<string, number> {
    const losses = new Map<string, number>()
    const add = (reason: string, count: number): void => {
        if (count > 0) {
            losses.set(reason, (losses.get(reason) ?? 0) + count)
        }
    }
    for (const drop of error.drops) {
        // The detail becomes a metric label, so an unexpected value from the far end must not add series without bound.
        add(drop.details && /^[a-z0-9_ ]{1,64}$/.test(drop.details) ? drop.details : 'other', 1)
    }
    add(UNDELIVERED, error.retryExhausted.length)
    return losses
}

const posthog = defaultConfig.POSTHOG_API_KEY
    ? new PostHog(defaultConfig.POSTHOG_API_KEY, {
          host: defaultConfig.POSTHOG_HOST_URL,
          enableExceptionAutocapture: false, // TODO - disabled while data volume is a problem, PS seems /extremely/ chatty exceptions wise
      })
    : null

// The client reports every event it loses only through this event, including events capture drops inside a 200 response.
posthog?.on('error', (error: unknown) => {
    if (!(error instanceof CaptureError)) {
        return
    }
    for (const [reason, count] of countCaptureLosses(error)) {
        captureEventsLostCounter.inc({ endpoint: error.endpoint, reason }, count)
    }
    logger.warn('⚠️', 'PostHog client lost events', { error: error.message })
})

if (process.env.NODE_ENV === 'test' && posthog) {
    void posthog.disable()
}

export function initSuperProperties(eventsIngestionPipeline: string | null = null): void {
    if (posthog) {
        const superProperties: Record<string, any> = {
            plugin_server_mode: defaultConfig.PLUGIN_SERVER_MODE,
            deployment: defaultConfig.CLOUD_DEPLOYMENT,
            plugin_server_events_ingestion_pipeline: eventsIngestionPipeline,
            // Super properties matching Python posthoganalytics.super_properties (posthog/apps.py)
            region: defaultConfig.CLOUD_DEPLOYMENT,
            service: defaultConfig.OTEL_SERVICE_NAME,
            environment: defaultConfig.OTEL_SERVICE_ENVIRONMENT,
        }

        try {
            // Docker containers should have a commit.txt file in the base directory with the git
            // commit hash used to generate them. `nodejs` runs from a child directory, so we
            // need to look up one level.
            superProperties['release'] = fs.readFileSync('../commit.txt', 'utf8')
        } catch {
            // The release isn't required, it's just nice to have.
        }

        void posthog.register(superProperties)
    }
}

export function captureTeamEvent(
    team: Team,
    event: string,
    properties: Record<string, any> = {},
    distinctId: string | null = null,
    client: PostHog | null = posthog
): void {
    if (client) {
        client.capture({
            distinctId: distinctId ?? team.uuid,
            event,
            properties: {
                team: team.uuid,
                ...properties,
            },
            groups: {
                project: team.uuid,
                organization: team.organization_id,
                instance: defaultConfig.SITE_URL,
            },
        })
    }
}

export async function isFeatureFlagEnabled(
    key: string,
    distinctId: string,
    options?: {
        groups?: Record<string, string>
        personProperties?: Record<string, string>
        groupProperties?: Record<string, Record<string, string>>
        onlyEvaluateLocally?: boolean
        sendFeatureFlagEvents?: boolean
    }
): Promise<boolean> {
    if (!posthog) {
        return false
    }

    try {
        const isEnabled = await posthog.isFeatureEnabled(key, distinctId, options)
        return isEnabled ?? false
    } catch (error) {
        // Log errors to aid debugging of feature flag evaluation issues (e.g. SES v1 vs v2 gating).
        console.error('Error evaluating PostHog feature flag', {
            key,
            distinctId,
            options,
            error,
        })
        return false
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
    tags: Record<string, Primitive>
    extra: Record<string, any>
}

export function captureException(exception: any, hint?: Partial<ExceptionHint>): void {
    if (posthog) {
        let additionalProperties = {}
        if (hint) {
            additionalProperties = {
                ...(hint.tags || {}),
                ...(hint.extra || {}),
            }
        }

        posthog.captureException(exception, { properties: additionalProperties })
    }
}
