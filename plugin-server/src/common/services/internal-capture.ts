import { DateTime } from 'luxon'

import { PluginsServerConfig } from '~/types'
import { internalFetch } from '~/utils/request'

export type InternalCaptureEvent = {
    team_id: number
    team_token: string
    event: string
    distinct_id: string
    properties?: Record<string, any>
    timestamp?: string
}

type CapturePayloadFormt = {
    api_key: string
    timestamp: string
    distinct_id: string
    sent_at: string
    event: string
    properties: Record<string, any>
}

export class InternalCaptureService {
    constructor(private config: PluginsServerConfig) {}

    get url(): string {
        return `${this.config.CAPTURE_INTERNAL_URL}/i/v0/e/`
    }

    isEnabled(): boolean {
        return this.config.CAPTURE_INTERNAL_URL !== ''
    }

    private prepareEvent(event: InternalCaptureEvent): CapturePayloadFormt {
        const properties = event.properties ?? {}
        properties['capture_internal'] = true
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

    async capture(event: InternalCaptureEvent): Promise<void> {
        await internalFetch(this.url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(this.prepareEvent(event)),
        })
    }

    async captureMany(events: InternalCaptureEvent[]): Promise<void> {
        await Promise.all(events.map(this.capture))
    }
}
