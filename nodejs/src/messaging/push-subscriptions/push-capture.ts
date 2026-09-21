import { randomUUID } from 'crypto'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

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
    constructor(
        private baseUrl: string,
        private timeoutMs: number = 2000
    ) {}

    /** Resolves only when capture accepted the event. The caller answers the SDK on that basis, and
     * an SDK that is told the registration was stored never sends it again. */
    public async capture(event: PushCaptureEvent): Promise<void> {
        const url = `${this.baseUrl}${CAPTURE_V1_INTERNAL_ENDPOINT}`
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

        const response = await internalFetch(url, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${event.token}`,
                'Content-Type': 'application/json',
                'User-Agent': SDK_INFO,
                'PostHog-Sdk-Info': SDK_INFO,
                'PostHog-Attempt': '1',
                'PostHog-Request-Id': randomUUID(),
                'PostHog-Request-Timestamp': now,
            },
            body: JSON.stringify({
                created_at: now,
                capture_internal: true,
                historical_migration: false,
                batch: [entry],
            }),
            timeoutMs: this.timeoutMs,
        })

        if (response.status < 200 || response.status >= 300) {
            captureCounter.inc({ outcome: 'rejected' })
            logger.warn('push_subscription_capture_rejected', { status: response.status })
            throw new Error(`capture returned ${response.status}`)
        }
        captureCounter.inc({ outcome: 'ok' })
    }
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
