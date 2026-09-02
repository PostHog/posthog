import { PostHog } from 'posthog-node'

import { Team } from '~/types'

import { defaultConfig } from '../config/config'
import { Limiter } from './token-bucket'

const fs = require('fs')

const posthog = defaultConfig.POSTHOG_API_KEY
    ? new PostHog(defaultConfig.POSTHOG_API_KEY, {
          host: defaultConfig.POSTHOG_HOST_URL,
          enableExceptionAutocapture: false, // TODO - disabled while data volume is a problem, PS seems /extremely/ chatty exceptions wise
      })
    : null

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

// A crash loop repeats one error signature once per Kafka message. Sample a burst,
// then throttle to one report per minute, so a dependency outage reports a handful of
// events plus a running suppressed count instead of hundreds of thousands of duplicates.
const EXCEPTION_SAMPLE_BURST = 5
const EXCEPTION_REPLENISH_PER_SECOND = 1 / 60

const exceptionSampleLimiter = new Limiter(EXCEPTION_SAMPLE_BURST, EXCEPTION_REPLENISH_PER_SECOND)
const suppressedExceptionCounts = new Map<string, number>()

// Collapse the variable parts of a message (addresses, ports, ids) so a crash loop
// with a changing endpoint or offset still maps to one signature.
function normalizeExceptionMessage(message: string): string {
    return message
        .replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '<ip>')
        .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '<uuid>')
        .replace(/\d+/g, '<n>')
        .slice(0, 200)
}

function exceptionSignature(exception: unknown): string {
    if (exception instanceof Error) {
        return `${exception.name}:${normalizeExceptionMessage(exception.message)}`
    }
    return normalizeExceptionMessage(String(exception))
}

// Decide whether to report this exception. Exported for testing.
export function sampleException(exception: unknown, now?: number): { capture: boolean; suppressed: number } {
    const signature = exceptionSignature(exception)

    if (!exceptionSampleLimiter.consume(signature, 1, now)) {
        suppressedExceptionCounts.set(signature, (suppressedExceptionCounts.get(signature) ?? 0) + 1)
        return { capture: false, suppressed: 0 }
    }

    const suppressed = suppressedExceptionCounts.get(signature) ?? 0
    if (suppressed > 0) {
        suppressedExceptionCounts.delete(signature)
    }
    return { capture: true, suppressed }
}

export function captureException(exception: any, hint?: Partial<ExceptionHint>): void {
    if (!posthog) {
        return
    }

    const { capture, suppressed } = sampleException(exception)
    if (!capture) {
        return
    }

    let additionalProperties: Record<string, any> = {}
    if (hint) {
        additionalProperties = {
            ...(hint.tags || {}),
            ...(hint.extra || {}),
        }
    }
    if (suppressed > 0) {
        additionalProperties.suppressed_since_previous_sample = suppressed
    }

    posthog.captureException(exception, undefined, additionalProperties)
}
