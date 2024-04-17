import { PreIngestionEvent, RawClickhouseHeatmapEvent, TimestampFormat } from 'types'
import { castTimestampOrNow } from 'utils/utils'

import { EventPipelineRunner } from './runner'

function isPositiveNumber(candidate: unknown): candidate is number {
    return typeof candidate === 'number' && candidate >= 0
}

export function extractHeatmapDataStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<[PreIngestionEvent, Promise<void>[]]> {
    const { eventUuid, teamId, timestamp, properties } = event
    const { $viewport_height, $viewport_width, $session_id, $heatmap_data, distinct_id } = properties || {}

    delete event.properties['$heatmap_data']

    if (!$heatmap_data || !isPositiveNumber($viewport_height) || !isPositiveNumber($viewport_width) || !$session_id) {
        return Promise.resolve([event, []])
    }

    const scale_factor = 16

    let heatmapEvents: RawClickhouseHeatmapEvent[] = []

    try {
        Object.entries($heatmap_data).forEach(([url, items]) => {
            if (Array.isArray(items)) {
                heatmapEvents = heatmapEvents.concat(
                    (items as any[]).map(
                        (hme: {
                            x: number
                            y: number
                            target_fixed: boolean
                            type: string
                        }): RawClickhouseHeatmapEvent => ({
                            type: hme.type,
                            x: Math.ceil(hme.x / scale_factor),
                            y: Math.ceil(hme.y / scale_factor),
                            pointer_target_fixed: hme.target_fixed,
                            viewport_height: Math.ceil($viewport_height / scale_factor),
                            viewport_width: Math.ceil($viewport_width / scale_factor),
                            current_url: url,
                            session_id: $session_id,
                            scale_factor,
                            timestamp: castTimestampOrNow(timestamp ?? null, TimestampFormat.ClickHouse),
                            team_id: teamId,
                            distinct_id: distinct_id,
                        })
                    )
                )
            }
        })
    } catch (e) {
        // TODO: Log error but don't exit
    }

    const acks = heatmapEvents.map((rawEvent) => {
        return runner.hub.kafkaProducer.produce({
            topic: runner.hub.CLICKHOUSE_JSON_EVENTS_KAFKA_TOPIC,
            key: eventUuid,
            value: Buffer.from(JSON.stringify(rawEvent)),
            waitForAck: true,
        })
    })

    return Promise.resolve([event, acks])
}
