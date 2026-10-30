import { Gauge } from 'prom-client'

import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult } from '../../types'

export const CAPTURE_BATCH_SIZE = 100
export const CAPTURE_BATCH_CONCURRENCY = 5

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

/**
 * Collects and flushes PostHog capture events emitted by hog function
 * invocations via `posthog.capture()`. Lifecycle mirrors the sibling
 * monitoring/warehouse services: `queueInvocationResults` extracts events from
 * the result batch, `flush()` drains them through the shared internal-capture
 * service.
 */
export class CapturedEventsService {
    private queuedEvents: InternalCaptureEvent[] = []

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
                const teams = new Map<number, Team | null>()
                for (const event of capturedEvents) {
                    if (!teams.has(event.team_id)) {
                        teams.set(event.team_id, await this.teamManager.getTeam(event.team_id))
                    }
                    const team = teams.get(event.team_id)
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

        // One source webhook request can now emit hundreds of events, so events are grouped per
        // team token into batch requests and sent a few batches at a time. Capture reads one token
        // per request body, which is why the grouping is per token and not per flush.
        const byToken = new Map<string, InternalCaptureEvent[]>()
        for (const event of events) {
            const group = byToken.get(event.team_token)
            if (group) {
                group.push(event)
            } else {
                byToken.set(event.team_token, [event])
            }
        }
        const batches: InternalCaptureEvent[][] = []
        for (const group of byToken.values()) {
            for (let i = 0; i < group.length; i += CAPTURE_BATCH_SIZE) {
                batches.push(group.slice(i, i + CAPTURE_BATCH_SIZE))
            }
        }
        for (let i = 0; i < batches.length; i += CAPTURE_BATCH_CONCURRENCY) {
            await Promise.all(
                batches.slice(i, i + CAPTURE_BATCH_CONCURRENCY).map((batch) =>
                    this.internalCaptureService.captureBatch(batch).catch((error) => {
                        logger.error('Error capturing internal events', { error, count: batch.length })
                        captureException(error)
                    })
                )
            )
        }
    }
}
