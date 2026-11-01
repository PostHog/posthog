import { groupBy } from 'lodash'
import { Gauge } from 'prom-client'

import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'

const capturedEventsPending = new Gauge({
    name: 'cdp_captured_events_pending',
    help: 'Number of internal capture events queued and waiting to be flushed. High values indicate accumulation and potential memory leak.',
})

const MAX_BATCH_BYTES = 2 * 1024 * 1024

function isSourceWebhookResult(result: CyclotronJobInvocationResult): boolean {
    return (
        (result.invocation as Partial<CyclotronJobInvocationHogFunction> | undefined)?.hogFunction?.type ===
        'source_webhook'
    )
}

function splitBySize(events: InternalCaptureEvent[]): InternalCaptureEvent[][] {
    const groups: InternalCaptureEvent[][] = []
    let group: InternalCaptureEvent[] = []
    let groupBytes = 0
    for (const event of events) {
        const eventBytes = JSON.stringify(event).length
        if (group.length > 0 && groupBytes + eventBytes > MAX_BATCH_BYTES) {
            groups.push(group)
            group = []
            groupBytes = 0
        }
        group.push(event)
        groupBytes += eventBytes
    }
    if (group.length > 0) {
        groups.push(group)
    }
    return groups
}

/**
 * Collects and flushes PostHog capture events emitted by hog function
 * invocations via `posthog.capture()`. Lifecycle mirrors the sibling
 * monitoring/warehouse services: `queueInvocationResults` extracts events from
 * the result batch, `flush()` drains them through the shared internal-capture
 * service.
 */
export class CapturedEventsService {
    private queuedGroups: InternalCaptureEvent[][] = []

    constructor(
        private internalCaptureService: InternalCaptureService,
        private teamManager: TeamManager
    ) {}

    /** Append already-resolved events onto the flush buffer. */
    queue(events: InternalCaptureEvent[]): void {
        for (const event of events) {
            this.queueGroup([event])
        }
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
        this.queueGroup([
            {
                team_token: team.api_token,
                event: event.event,
                distinct_id: event.distinct_id,
                timestamp: event.timestamp,
                properties: event.properties,
            },
        ])
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
                const events: InternalCaptureEvent[] = []
                for (const event of capturedEvents) {
                    const team = await this.teamManager.getTeam(event.team_id)
                    if (!team) {
                        continue
                    }
                    events.push({
                        team_token: team.api_token,
                        event: event.event,
                        distinct_id: event.distinct_id,
                        timestamp: event.timestamp,
                        properties: event.properties,
                    })
                }
                if (!isSourceWebhookResult(result)) {
                    this.queue(events)
                    return
                }
                for (const teamEvents of Object.values(groupBy(events, (event) => event.team_token))) {
                    splitBySize(teamEvents).forEach((group) => this.queueGroup(group))
                }
            })
        )
    }

    // Required by ResultSink. This sink holds nothing of its own: it writes through the shared
    // Kafka outputs, which the server disconnects separately on shutdown.
    async stop(): Promise<void> {
        return Promise.resolve()
    }

    async flush(): Promise<void> {
        const groups = this.queuedGroups
        this.queuedGroups = []
        capturedEventsPending.set(0)

        await Promise.all(groups.map((group) => this.sendAndReport(group)))
    }

    private queueGroup(group: InternalCaptureEvent[]): void {
        this.queuedGroups.push(group)
        capturedEventsPending.inc(group.length)
    }

    private async sendAndReport(group: InternalCaptureEvent[]): Promise<void> {
        try {
            await this.send(group)
        } catch (error) {
            logger.error('Error capturing internal event', { error })
            captureException(error)
        }
    }

    private async send(group: InternalCaptureEvent[]): Promise<void> {
        if (group.length === 1) {
            await this.internalCaptureService.capture(group[0])
            return
        }
        const response = await this.internalCaptureService.captureBatch(group)
        if (response.status === 400) {
            await Promise.all(group.map((event) => this.sendAndReport([event])))
        } else if (response.status >= 300) {
            logger.warn('Capture refused an internal event batch', { status: response.status, events: group.length })
        }
    }
}
