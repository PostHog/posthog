import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'
import { RetrySchedule, retryIfRetriable } from '~/common/utils/retries'

const internalCaptureCounter = new Counter({
    name: 'internal_capture_events',
    help: 'Number of internal capture events',
    labelNames: ['status'],
})

const internalCaptureAttemptFailureCounter = new Counter({
    name: 'internal_capture_event_attempt_failures',
    help: 'Internal capture attempts that failed, by reason. An event can fail several attempts before it succeeds.',
    labelNames: ['reason'],
})

// Capture sits next to the worker in the cluster, so a failure is short lived. Two retries cover a rolling restart or
// a dropped connection without holding a flush open: an attempt takes at most EXTERNAL_REQUEST_TIMEOUT_MS.
const CAPTURE_RETRY_SCHEDULE: RetrySchedule = {
    tries: 3,
    sleepMs: 50,
    backoffFactor: 4,
    maxSleepMs: 1000,
    softDeadlineMs: 5000,
}

export type InternalCaptureEvent = {
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

type CapturePayloadFormat = {
    api_key: string
    timestamp: string
    distinct_id: string
    sent_at: string
    event: string
    properties: Record<string, any>
}

/** Capture rejected the event itself. A retry sends the same payload, so it gets the same answer. */
class CaptureRejectedError extends Error {
    readonly isRetriable = false
    constructor(readonly status: number) {
        super(`Internal capture rejected the event with status ${status}`)
        this.name = 'CaptureRejectedError'
    }
}

/** Capture was unavailable or overloaded. A later attempt can still land the event. */
class CaptureUnavailableError extends Error {
    constructor(readonly status: number) {
        super(`Internal capture is unavailable, status ${status}`)
        this.name = 'CaptureUnavailableError'
    }
}

/** Undici reports a transport failure through `code`, for example a connect timeout. */
function failureReason(error: unknown): string {
    if (error instanceof CaptureUnavailableError || error instanceof CaptureRejectedError) {
        return `status_${error.status}`
    }
    const code = (error as { code?: unknown })?.code
    return typeof code === 'string' ? code : 'error'
}

export class InternalCaptureService {
    constructor(private config: Pick<CommonConfig, 'CAPTURE_INTERNAL_URL'>) {}

    private prepareEvent(event: InternalCaptureEvent): CapturePayloadFormat {
        const properties = { ...(event.properties ?? {}), capture_internal: true }
        const now = DateTime.utc().toISO()
        return {
            api_key: event.team_token,
            timestamp: event.timestamp ?? now,
            distinct_id: event.distinct_id,
            sent_at: now,
            event: event.event,
            properties,
        }
    }

    /**
     * One POST to capture. The body is always drained: undici holds the socket open until the body is read, so a
     * caller that ignores it makes every capture open a new connection and the pool runs out.
     */
    private async send(body: string): Promise<number> {
        const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body,
        })
        await response.dump()

        if (response.status === 429 || response.status >= 500) {
            throw new CaptureUnavailableError(response.status)
        }
        if (response.status >= 400) {
            throw new CaptureRejectedError(response.status)
        }
        return response.status
    }

    /** Resolves when capture accepted the event. Throws when every attempt failed, so the caller can count the loss. */
    async capture(event: InternalCaptureEvent): Promise<void> {
        logger.debug('Capturing internal event', { event, url: this.config.CAPTURE_INTERNAL_URL })
        const body = JSON.stringify(this.prepareEvent(event))

        try {
            const status = await retryIfRetriable(async () => {
                try {
                    return await this.send(body)
                } catch (error) {
                    internalCaptureAttemptFailureCounter.inc({ reason: failureReason(error) })
                    throw error
                }
            }, CAPTURE_RETRY_SCHEDULE)

            logger.debug('Internal capture event captured', { status })
            internalCaptureCounter.inc({ status: status.toString() })
        } catch (e) {
            // A rejection keeps its status, so the counter still separates a bad token from capture being unreachable.
            internalCaptureCounter.inc({ status: e instanceof CaptureRejectedError ? e.status.toString() : 'error' })
            logger.error('Error capturing internal event', { error: e })
            throw e
        }
    }
}
