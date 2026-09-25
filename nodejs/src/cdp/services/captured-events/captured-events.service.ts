import { Counter, Gauge } from 'prom-client'

import {
    InternalCaptureEvent,
    InternalCaptureService,
    MAX_EVENTS_PER_CAPTURE_REQUEST,
} from '~/common/services/internal-capture'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { CyclotronJobInvocationResult } from '../../types'

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

const capturedEventsDropped = new Counter({
    name: 'cdp_captured_events_dropped',
    help: 'Internal capture events lost because every attempt to send them failed.',
})

// A flush already costs one request per team. The cap covers a worker that serves many teams at once, so the
// requests never grow into a burst of connections that capture cannot accept.
const MAX_CONCURRENT_CAPTURE_REQUESTS = 16

/** Groups a flush into the requests it takes: one per team, split again when a team has more events than one holds. */
function requestsFor(events: InternalCaptureEvent[]): [string, InternalCaptureEvent[]][] {
    const byTeam = new Map<string, InternalCaptureEvent[]>()
    for (const event of events) {
        const existing = byTeam.get(event.team_token)
        if (existing) {
            existing.push(event)
        } else {
            byTeam.set(event.team_token, [event])
        }
    }

    const requests: [string, InternalCaptureEvent[]][] = []
    for (const [teamToken, teamEvents] of byTeam) {
        for (let i = 0; i < teamEvents.length; i += MAX_EVENTS_PER_CAPTURE_REQUEST) {
            requests.push([teamToken, teamEvents.slice(i, i + MAX_EVENTS_PER_CAPTURE_REQUEST)])
        }
    }
    return requests
}

/**
 * Collects and flushes PostHog capture events emitted by hog function
 * invocations via `posthog.capture()`. Lifecycle mirrors the sibling
 * monitoring/warehouse services: `queueInvocationResults` extracts events from
 * the result batch, `flush()` drains them through the shared internal-capture
 * service.
 */
export class CapturedEventsService {
    private queuedEvents: InternalCaptureEvent[] = []

    // Held on the service, so overlapping flushes share one budget rather than each taking their own.
    private inFlight = new ConcurrencyController(MAX_CONCURRENT_CAPTURE_REQUESTS)

    constructor(
        private internalCaptureService: InternalCaptureService,
        private teamManager: TeamManager
    ) {}

    /** Append already-resolved events onto the flush buffer. */
    queue(events: InternalCaptureEvent[]): void {
        if (events.length === 0) {
            return
        }
        for (const event of events) {
            this.queuedEvents.push(event)
        }
        capturedEventsPending.set(this.queuedEvents.length)
    }

    /**
     * Resolve the team for a single event (to obtain the API token) and queue it.
     * Used by code paths outside the invocation-result lifecycle, e.g. SES webhooks.
     */
    async queueEvent(event: { team_id: number } & Omit<InternalCaptureEvent, 'team_token'>): Promise<void> {
        const team = await this.teamManager.getTeam(event.team_id)
        if (!team) {
            return
        }
        this.queuedEvents.push({
            team_token: team.api_token,
            event: event.event,
            distinct_id: event.distinct_id,
            timestamp: event.timestamp,
            properties: event.properties,
        })
        capturedEventsPending.set(this.queuedEvents.length)
    }

    /**
     * Extract `capturedPostHogEvents` from each result, resolve the team
     * (to obtain the API token used by capture), and queue.
     */
    async queueInvocationResults(results: CyclotronJobInvocationResult[]): Promise<void> {
        await Promise.all(
            results.map(async (result) => {
                const capturedEvents = result.capturedPostHogEvents
                if (!capturedEvents || capturedEvents.length === 0) {
                    return
                }
                for (const event of capturedEvents) {
                    const team = await this.teamManager.getTeam(event.team_id)
                    if (!team) {
                        continue
                    }
                    this.queuedEvents.push({
                        team_token: team.api_token,
                        event: event.event,
                        distinct_id: event.distinct_id,
                        timestamp: event.timestamp,
                        properties: event.properties,
                    })
                }
                capturedEventsPending.set(this.queuedEvents.length)
            })
        )
    }

    // Required by ResultSink. This sink holds nothing of its own: it writes through the shared
    // Kafka outputs, which the server disconnects separately on shutdown.
    async stop(): Promise<void> {
        return Promise.resolve()
    }

    async flush(): Promise<void> {
        const events = this.queuedEvents
        this.queuedEvents = []
        capturedEventsPending.set(0)

        if (events.length === 0) {
            return
        }

        let dropped = 0
        let firstError: unknown

        await Promise.all(
            requestsFor(events).map(([teamToken, teamEvents]) =>
                this.inFlight
                    .run({
                        fn: () => this.internalCaptureService.captureBatch(teamToken, teamEvents),
                        debugTag: 'internal-capture',
                    })
                    .catch((error) => {
                        dropped += teamEvents.length
                        firstError = firstError ?? error
                    })
            )
        )

        if (dropped > 0) {
            capturedEventsDropped.inc(dropped)
            // One report per flush. Capture is down for the whole flush or for none of it, so a report per request
            // would say the same thing thousands of times over.
            logger.error('Error capturing internal events', {
                dropped,
                queued: events.length,
                error: String(firstError),
            })
            captureException(firstError)
        }
    }
}
