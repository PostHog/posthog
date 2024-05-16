import { FeatureExtractionPipeline, FeatureExtractionPipelineOptions } from '@xenova/transformers'
import { URL } from 'url'

import { PreIngestionEvent, RawClickhouseHeatmapEvent, TimestampFormat } from '../../../types'
import { castTimestampOrNow } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

// This represents the scale factor for the heatmap data. Essentially how much we are reducing the resolution by.
const SCALE_FACTOR = 16

type HeatmapDataItem = {
    x: number
    y: number
    target_fixed: boolean
    type: string
}

type HeatmapData = Record<string, HeatmapDataItem[]>

let featureExtractionPipeline: FeatureExtractionPipeline
const embeddingsPipeline = async (): Promise<FeatureExtractionPipeline> => {
    if (!featureExtractionPipeline) {
        // a little magic here to both delay the slow import until the first time it is needed
        // and to make it work due to some ESM/commonjs faff
        const TransformersApi = Function('return import("@xenova/transformers")')()
        const { pipeline } = await TransformersApi
        featureExtractionPipeline = await pipeline('feature-extraction', 'Xenova/gte-small')
    }
    return Promise.resolve(featureExtractionPipeline)
}

export async function embedLogs(
    runner: EventPipelineRunner,
    event: PreIngestionEvent,
    precision = 7
): Promise<PreIngestionEvent> {
    if (event.event !== '$log') {
        return Promise.resolve(event)
    }

    const options: FeatureExtractionPipelineOptions = { pooling: 'mean', normalize: false }
    const currentPipeline = await embeddingsPipeline()
    const output = await currentPipeline(
        `${event.properties['$msg']}-${event.properties['$namespace']}-${event.properties['$level']}`,
        options
    )
    const roundedOutput = Array.from(output.data as number[]).map((value: number) =>
        parseFloat(value.toFixed(precision))
    )
    event.properties['$embedding'] = roundedOutput
    return event
}

export function extractHeatmapDataStep(
    runner: EventPipelineRunner,
    event: PreIngestionEvent
): Promise<[PreIngestionEvent, Promise<void>[]]> {
    const { eventUuid, teamId } = event

    let acks: Promise<void>[] = []

    try {
        const heatmapEvents = extractScrollDepthHeatmapData(event) ?? []

        // eslint-disable-next-line @typescript-eslint/no-floating-promises
        acks = heatmapEvents.map((rawEvent) => {
            return runner.hub.kafkaProducer.produce({
                topic: runner.hub.CLICKHOUSE_HEATMAPS_KAFKA_TOPIC,
                key: eventUuid,
                value: Buffer.from(JSON.stringify(rawEvent)),
                waitForAck: true,
            })
        })
    } catch (e) {
        acks.push(
            captureIngestionWarning(runner.hub.kafkaProducer, teamId, 'invalid_heatmap_data', {
                eventUuid,
            })
        )
    }

    // We don't want to ingest this data to the events table
    delete event.properties['$heatmap_data']

    return Promise.resolve([event, acks])
}

function replacePathInUrl(url: string, newPath: string): string {
    const parsedUrl = new URL(url)
    parsedUrl.pathname = newPath
    return parsedUrl.toString()
}

function extractScrollDepthHeatmapData(event: PreIngestionEvent): RawClickhouseHeatmapEvent[] {
    const { teamId, timestamp, properties } = event
    const {
        $viewport_height,
        $viewport_width,
        $session_id,
        distinct_id,
        $prev_pageview_pathname,
        $prev_pageview_max_scroll,
        $current_url,
        $heatmap_data,
    } = properties || {}

    let heatmapData = $heatmap_data as HeatmapData | null

    if ($prev_pageview_pathname && $current_url) {
        // We are going to add the scroll depth info derived from the previous pageview to the current pageview's heatmap data
        if (!heatmapData) {
            heatmapData = {}
        }

        const previousUrl = replacePathInUrl($current_url, $prev_pageview_pathname)
        heatmapData[previousUrl] = heatmapData[previousUrl] || []
        heatmapData[previousUrl].push({
            x: 0,
            y: $prev_pageview_max_scroll,
            target_fixed: false,
            type: 'scrolldepth',
        })
    }

    let heatmapEvents: RawClickhouseHeatmapEvent[] = []

    if (!heatmapData) {
        return []
    }

    Object.entries(heatmapData).forEach(([url, items]) => {
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
                        x: Math.round(hme.x / SCALE_FACTOR),
                        y: Math.round(hme.y / SCALE_FACTOR),
                        pointer_target_fixed: hme.target_fixed,
                        viewport_height: Math.round($viewport_height / SCALE_FACTOR),
                        viewport_width: Math.round($viewport_width / SCALE_FACTOR),
                        current_url: url,
                        session_id: $session_id,
                        scale_factor: SCALE_FACTOR,
                        timestamp: castTimestampOrNow(timestamp ?? null, TimestampFormat.ClickHouse),
                        team_id: teamId,
                        distinct_id: distinct_id,
                    })
                )
            )
        }
    })

    return heatmapEvents
}
