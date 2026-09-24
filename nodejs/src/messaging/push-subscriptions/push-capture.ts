import { randomUUID } from 'crypto'
import { Counter } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { FetchResponse, internalFetch } from '~/common/utils/request'

/** Submits the person update through the same capture path Django uses.
 *
 * The plugin server's shared `InternalCaptureService` posts a single flat event to the public
 * capture endpoint, with no Authorization header. Django posts a v1 batch envelope carrying
 * `capture_internal: true` to `/i/v1/analytics/events` with the project token as a bearer. Those are
 * different doors into ingestion: the internal one is how an event submitted on a customer's behalf
 * is marked as such, and quota and routing read that marking. Serving this endpoint from Node
 * through the public door would change how the same registration is ingested and counted, which is
 * not a change this move is supposed to make.
 */

const SDK_INFO = 'posthog-capture-v1-internal/1.0'
const CAPTURE_V1_INTERNAL_ENDPOINT = '/i/v1/analytics/events'

/** The v1 option fields whose legacy spelling has to be lifted out of `properties`, or capture-rs
 * reads them as ordinary event properties and the option goes unapplied. */
const OPTIONS_TO_LEGACY_PROPERTY: Record<string, string> = {
    cookieless_mode: '$cookieless_mode',
    disable_skew_correction: '$ignore_sent_at',
    product_tour_id: '$product_tour_id',
    process_person_profile: '$process_person_profile',
}
const EXTRA_LEGACY_ALIASES: Record<string, string> = {
    disable_skew_correction: 'disable_skew_adjustment',
}

const captureCounter = new Counter({
    name: 'push_subscription_capture_total',
    help: 'Person updates submitted for a device registration, by outcome.',
    labelNames: ['outcome'],
})

export type PushCaptureEvent = {
    token: string
    event: string
    distinctId: string
    properties: Record<string, any>
}

export class PushCaptureService {
    private origin: string

    constructor(
        captureUrl: string,
        private timeoutMs: number = 2000,
        private sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
    ) {
        // The plugin server's CAPTURE_INTERNAL_URL ends in the `/capture` path of the v0 endpoint, while
        // Django's is the bare origin. The v1 path goes on the origin, so either form works.
        this.origin = new URL(captureUrl).origin
    }

    /** Resolves only when capture accepted the event. The caller answers the SDK on that basis, and
     * an SDK that is told the registration was stored never sends it again. */
    public async capture(event: PushCaptureEvent): Promise<void> {
        const now = new Date().toISOString()
        const { options, properties } = splitOptions(event.properties)

        const entry: Record<string, any> = {
            event: event.event,
            uuid: randomUUID(),
            distinct_id: event.distinctId,
            timestamp: now,
            properties,
        }
        if (Object.keys(options).length > 0) {
            entry.options = options
        }
        const body = JSON.stringify({
            created_at: now,
            capture_internal: true,
            historical_migration: false,
            batch: [entry],
        })

        for (let attempt = 1; ; attempt++) {
            const response = await this.post(event.token, body, attempt)

            if (response.status < 200 || response.status >= 300) {
                captureCounter.inc({ outcome: 'rejected' })
                logger.warn('push_subscription_capture_rejected', { status: response.status })
                throw new Error(`capture returned ${response.status}`)
            }

            if (resultFor(await response.text(), entry.uuid) !== 'retry') {
                captureCounter.inc({ outcome: 'ok' })
                return
            }
            if (attempt >= MAX_ATTEMPTS) {
                captureCounter.inc({ outcome: 'rejected' })
                logger.warn('push_subscription_capture_rejected', { status: response.status, result: 'retry' })
                throw new Error('capture asked to retry the event on every attempt')
            }
            await this.sleep(retryAfterMs(response.headers['retry-after']))
        }
    }

    /** One application attempt, with the transport retries Django's session makes under it. A timeout
     * is not retried: each attempt already holds the SDK's request for the full timeout, and retrying
     * one is what stretches Django's answer to many seconds while capture is slow. */
    private async post(token: string, body: string, attempt: number): Promise<FetchResponse> {
        for (let retry = 0; ; retry++) {
            try {
                const response = await internalFetch(`${this.origin}${CAPTURE_V1_INTERNAL_ENDPOINT}`, {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${token}`,
                        'Content-Type': 'application/json',
                        'User-Agent': SDK_INFO,
                        'PostHog-Sdk-Info': SDK_INFO,
                        'PostHog-Attempt': String(attempt),
                        'PostHog-Request-Id': randomUUID(),
                        'PostHog-Request-Timestamp': new Date().toISOString(),
                    },
                    body,
                    timeoutMs: this.timeoutMs,
                })
                if (!TRANSPORT_RETRY_STATUSES.has(response.status) || retry >= TRANSPORT_BACKOFF_MS.length) {
                    return response
                }
                await response.text()
            } catch (error) {
                if ((error as Error).name === 'TimeoutError' || retry >= TRANSPORT_BACKOFF_MS.length) {
                    throw error
                }
            }
            await this.sleep(TRANSPORT_BACKOFF_MS[retry])
        }
    }
}

/** Django's session retries these statuses and connection errors three times, backing off 0, 200 and
 * 400ms (urllib3 `Retry(total=3, backoff_factor=0.1)`). */
const TRANSPORT_RETRY_STATUSES = new Set([500, 502, 503, 504])
const TRANSPORT_BACKOFF_MS = [0, 200, 400]

/** Django's `CAPTURE_V1_INTERNAL_MAX_ATTEMPTS` and `CAPTURE_V1_INTERNAL_RETRY_AFTER_CAP_SECONDS`. */
const MAX_ATTEMPTS = 4
const RETRY_AFTER_CAP_MS = 5000

function resultFor(text: string, uuid: string): string | undefined {
    try {
        const result = parseJSON(text)?.results?.[uuid]?.result
        return typeof result === 'string' ? result : undefined
    } catch {
        return undefined
    }
}

/** Seconds, capped, as Django's `_parse_retry_after` reads it: absent is 0, unparseable is 1. */
function retryAfterMs(header: string | undefined): number {
    if (!header) {
        return 0
    }
    const seconds = Number(header)
    if (!Number.isFinite(seconds)) {
        return 1000
    }
    return Math.min(Math.max(seconds * 1000, 0), RETRY_AFTER_CAP_MS)
}

function splitOptions(input: Record<string, any>): { options: Record<string, any>; properties: Record<string, any> } {
    const properties = { ...input }
    const options: Record<string, any> = {}

    for (const [optionKey, legacyProperty] of Object.entries(OPTIONS_TO_LEGACY_PROPERTY)) {
        let value = properties[legacyProperty]
        delete properties[legacyProperty]

        const alias = EXTRA_LEGACY_ALIASES[optionKey]
        if (alias) {
            const aliasValue = properties[alias]
            delete properties[alias]
            if (value === undefined || value === null) {
                value = aliasValue
            }
        }

        if (value !== undefined && value !== null) {
            options[optionKey] = value
        }
    }

    for (const field of ['$session_id', '$window_id']) {
        delete properties[field]
    }

    return { options, properties }
}
