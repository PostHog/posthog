import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { StatsD } from 'hot-shots'

enum EventPropertyType {
    Number = 'NUMBER',
    String = 'STRING',
    Boolean = 'BOOLEAN',
    DateTime = 'DATETIME',
}

interface EventPropertiesCounter {
    createdAt: number
    lastSeenAt: number
    totalVolume: number
    propertyType: EventPropertyType | null
    propertyTypeFormat: string | null
}

interface EventNamePropertiesBuffer {
    totalVolume: number
    uniqueVolume: number
    buffer: Map<TeamId, Map<string, EventPropertiesCounter>>
}

export class EventPropertyCounter {
    db: DB
    eventPropertiesBuffer: EventNamePropertiesBuffer
    lastFlushAt: DateTime
    statsd?: StatsD

    constructor(db: DB, statsd?: StatsD) {
        this.db = db
        this.statsd = statsd
        this.eventPropertiesBuffer = { totalVolume: 0, uniqueVolume: 0, buffer: new Map() }
        this.lastFlushAt = DateTime.now()
    }

    public async updateEventPropertyCounter(teamId: number, event: string, properties: Properties): Promise<void> {
        this.updateEventPropertiesBuffer(teamId, event, properties)
        // Flush every 2 minutes or 50k unique properties, whichever comes first.
        // Additionally, a flush is broadcast every 1 minute from pluginServer.
        if (
            this.eventPropertiesBuffer.uniqueVolume > 50000 ||
            DateTime.now().diff(this.lastFlushAt).as('seconds') > 120
        ) {
            await this.flush()
        }
    }

    /** Save information about event properties into a custom buffer */
    public updateEventPropertiesBuffer(teamId: number, event: string, properties: Record<string, any>): void {
        const timestamp = new DateTime().toSeconds()
        let bufferForTeam = this.eventPropertiesBuffer.buffer.get(teamId)
        if (!bufferForTeam) {
            bufferForTeam = new Map()
            this.eventPropertiesBuffer.buffer.set(teamId, bufferForTeam)
        }
        for (const [property, value] of Object.entries(properties)) {
            const key = JSON.stringify([event, property])
            let propertyBuffer = bufferForTeam.get(key)
            if (!propertyBuffer) {
                propertyBuffer = {
                    createdAt: timestamp,
                    lastSeenAt: timestamp,
                    totalVolume: 1,
                    propertyType: null,
                    propertyTypeFormat: null,
                }
                bufferForTeam.set(key, propertyBuffer)
                this.eventPropertiesBuffer.uniqueVolume += 1
            } else {
                propertyBuffer.createdAt = Math.min(timestamp, propertyBuffer.createdAt)
                propertyBuffer.lastSeenAt = Math.max(timestamp, propertyBuffer.lastSeenAt)
                propertyBuffer.totalVolume += 1
            }
            this.eventPropertiesBuffer.totalVolume += 1

            propertyBuffer.propertyType =
                typeof value === 'number'
                    ? EventPropertyType.Number
                    : typeof value === 'boolean'
                    ? EventPropertyType.Boolean
                    : typeof value === 'string'
                    ? EventPropertyType.String
                    : null
            propertyBuffer.propertyTypeFormat = null

            if (propertyBuffer.propertyType === EventPropertyType.String) {
                const dateFormat = detectDateFormat(value)
                if (dateFormat) {
                    propertyBuffer.propertyType = EventPropertyType.DateTime
                    propertyBuffer.propertyTypeFormat = dateFormat
                }
            }
        }
    }

    public async flush(): Promise<void> {
        if (this.eventPropertiesBuffer.totalVolume === 0) {
            return
        }
        const timeout = timeoutGuard(
            `Still flushing the event names and properties buffer. Timeout warning after 30 sec!`
        )
        try {
            const startTime = DateTime.now()
            const lastFlushedSecondsAgo = DateTime.now().diff(this.lastFlushAt).as('seconds')
            const cacheSize = this.eventPropertiesBuffer.uniqueVolume
            status.info(
                `🚽 Starting flushEventPropertyCounter. Cache size: ${cacheSize} items. Last flushed: ${lastFlushedSecondsAgo} seconds ago.`
            )

            const oldBuffer = this.eventPropertiesBuffer
            this.eventPropertiesBuffer = { totalVolume: 0, uniqueVolume: 0, buffer: new Map() }
            this.lastFlushAt = DateTime.now()

            let i = 0
            let queryValues: string[] = []
            let params: any[] = []

            for (const [teamId, teamBuffer] of oldBuffer.buffer.entries()) {
                for (const [key, propertyBuffer] of teamBuffer.entries()) {
                    const [event, property] = JSON.parse(key)
                    const { propertyType, propertyTypeFormat, totalVolume, lastSeenAt, createdAt } = propertyBuffer
                    queryValues.push(`($${++i},$${++i},$${++i},$${++i},$${++i},$${++i},$${++i},$${++i})`)
                    params.push(
                        teamId,
                        event,
                        property,
                        propertyType,
                        propertyTypeFormat,
                        totalVolume,
                        DateTime.fromSeconds(createdAt),
                        DateTime.fromSeconds(lastSeenAt)
                    )
                }
            }

            await this.db.postgresQuery(
                `INSERT INTO posthog_eventproperty(team_id, event, property, property_type, property_type_format,
                                                   total_volume, created_at, last_seen_at)
                 VALUES ${queryValues.join(',')} ON CONFLICT
                 ON CONSTRAINT posthog_eventproperty_team_id_event_property_10910b3b_uniq DO
                UPDATE SET
                    total_volume = posthog_eventproperty.total_volume + excluded.total_volume,
                    created_at = LEAST(posthog_eventproperty.created_at, excluded.created_at),
                    last_seen_at = GREATEST(posthog_eventproperty.last_seen_at, excluded.last_seen_at),
                    property_type = CASE WHEN posthog_eventproperty.property_type IS NULL THEN excluded.property_type ELSE posthog_eventproperty.property_type
                END,
                property_type_format = CASE WHEN posthog_eventproperty.property_type_format IS NULL THEN excluded.property_type_format ELSE posthog_eventproperty.property_type_format
                END
                `,
                params,
                'eventPropertyCounterFlush'
            )

            const elapsedTime = DateTime.now().diff(startTime).as('milliseconds')
            this.statsd?.set('flushEventPropertyCounter.Size', cacheSize)
            this.statsd?.set('flushEventPropertyCounter.QuerySize', params.length)
            this.statsd?.timing('flushEventPropertyCounter', elapsedTime)
            status.info(`✅ 🚽 flushEventPropertyCounter finished successfully in ${elapsedTime} ms.`)
        } finally {
            clearTimeout(timeout)
        }
    }
}

function detectDateFormat(value: string): string | void {
    if (value.match(/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/)) {
        return 'YYYY-MM-DD'
    }
}
