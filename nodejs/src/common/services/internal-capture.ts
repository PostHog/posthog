import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { CommonConfig } from '~/common/config'
import { logger } from '~/common/utils/logger'
import { FetchResponse, internalFetch } from '~/common/utils/request'
import { sleep } from '~/common/utils/utils'

const internalCaptureCounter = new Counter({
    name: 'internal_capture_events',
    help: 'Number of internal capture events',
    labelNames: ['status'],
})

// getaddrinfo failures we treat as transient in-cluster DNS blips: worth a quick
// retry, not worth paging error tracking. Kept narrow on purpose so genuine
// capture-service outages still surface.
const TRANSIENT_NETWORK_ERROR_CODES = ['EAI_AGAIN', 'ENOTFOUND']

/**
 * True when `err` (or anything in its `cause` chain) looks like a transient
 * DNS/network failure. undici wraps the underlying system error in `cause`, so
 * we walk the chain and check both `.code` and the message text.
 */
export function isTransientNetworkError(err: unknown): boolean {
    let current: unknown = err
    for (let depth = 0; current && typeof current === 'object' && depth < 5; depth++) {
        const e = current as { code?: unknown; message?: unknown; cause?: unknown }
        const message = e.message
        if (typeof e.code === 'string' && TRANSIENT_NETWORK_ERROR_CODES.includes(e.code)) {
            return true
        }
        if (typeof message === 'string' && TRANSIENT_NETWORK_ERROR_CODES.some((code) => message.includes(code))) {
            return true
        }
        current = e.cause
    }
    return false
}

export type InternalCaptureEvent = {
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

export type InternalCaptureRetryOptions = {
    maxRetries: number
    baseDelayMs: number
}

const DEFAULT_RETRY_OPTIONS: InternalCaptureRetryOptions = {
    maxRetries: 3,
    baseDelayMs: 100,
}

type CapturePayloadFormat = {
    api_key: string
    timestamp: string
    distinct_id: string
    sent_at: string
    event: string
    properties: Record<string, any>
}

export class InternalCaptureService {
    constructor(
        private config: Pick<CommonConfig, 'CAPTURE_INTERNAL_URL'>,
        private retryOptions: InternalCaptureRetryOptions = DEFAULT_RETRY_OPTIONS
    ) {}

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

    async capture(event: InternalCaptureEvent): Promise<FetchResponse> {
        logger.debug('Capturing internal event', { event, url: this.config.CAPTURE_INTERNAL_URL })
        const body = JSON.stringify(this.prepareEvent(event))

        for (let attempt = 0; ; attempt++) {
            try {
                const response = await internalFetch(this.config.CAPTURE_INTERNAL_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body,
                })
                logger.debug('Internal capture event captured', { status: response.status })

                internalCaptureCounter.inc({ status: response.status.toString() })
                return response
            } catch (e) {
                // Transient in-cluster DNS blips get a bounded retry with backoff so a
                // brief hiccup recovers on its own instead of failing the capture.
                if (isTransientNetworkError(e) && attempt < this.retryOptions.maxRetries) {
                    internalCaptureCounter.inc({ status: 'retry' })
                    await sleep(this.retryOptions.baseDelayMs * 2 ** attempt)
                    continue
                }

                internalCaptureCounter.inc({ status: 'error' })
                logger.error('Error capturing internal event', { error: e })
                throw e
            }
        }
    }
}
