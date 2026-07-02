import { Message } from 'node-rdkafka'
import { URL } from 'url'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { logger } from '~/common/utils/logger'
import { castTimestampOrNow } from '~/common/utils/utils'
import { isDistinctIdIllegal } from '~/ingestion/common/persons/person-merge-service'
import { EmitEventStepOutput, IngestedEventInfo } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { PipelineWarning } from '~/ingestion/framework/pipeline.interface'
import { PipelineResult, drop, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { EventHeaders, PreIngestionEvent, RawClickhouseHeatmapEvent, TimestampFormat } from '~/types'

import { HEATMAPS_OUTPUT, HeatmapsOutput } from './outputs'

export interface ExtractHeatmapDataStepInput {
    preparedEvent: PreIngestionEvent
    headers: EventHeaders
    message: Message
}

/**
 * Terminal step of the heatmaps pipeline: extracts heatmap data and produces it to
 * Kafka. The event itself is not emitted onwards, so only the `ingested` handles
 * (for the lag step) are returned — see EmitEventStepOutput.
 */
export function createExtractHeatmapDataStep<TInput extends ExtractHeatmapDataStepInput>(
    outputs: IngestionOutputs<HeatmapsOutput>
): ProcessingStep<TInput, EmitEventStepOutput> {
    return async function extractHeatmapDataStep(input: TInput): Promise<PipelineResult<EmitEventStepOutput>> {
        const { preparedEvent, headers, message } = input
        const { eventUuid } = preparedEvent

        // When capture has already redirected heatmap data to the heatmaps topic,
        // skip extraction here — capture strips $heatmap_data before publishing.
        if (headers.skip_heatmap_processing) {
            return Promise.resolve(ok({ ingested: [] }))
        }

        const acks: Promise<void>[] = []
        const ingested: Promise<IngestedEventInfo | null>[] = []
        const warnings: PipelineWarning[] = []

        const ingestedInfo: IngestedEventInfo = {
            capturedAt: headers.now,
            topic: message.topic,
            partition: message.partition,
        }

        try {
            const extractResult = extractScrollDepthHeatmapData(preparedEvent)

            if (!isOkResult(extractResult)) {
                return extractResult
            }

            const { heatmapEvents, warnings: extractWarnings } = extractResult.value
            warnings.push(...extractWarnings)

            if (heatmapEvents.length > 0) {
                const ack = outputs.queueMessages(
                    HEATMAPS_OUTPUT,
                    heatmapEvents.map((rawEvent) => ({
                        key: eventUuid,
                        value: Buffer.from(JSON.stringify(rawEvent)),
                        teamId: preparedEvent.teamId,
                    }))
                )
                acks.push(ack)
                // Self-handle the lag-tracking branch so a produce failure can never surface
                // as an unhandled rejection: a failed produce resolves to null (no lag sample).
                // The raw `ack` in side effects still carries the error for normal handling.
                ingested.push(
                    ack.then(
                        () => ingestedInfo,
                        () => null
                    )
                )
            }
        } catch {
            warnings.push({
                type: 'invalid_heatmap_data',
                details: {
                    eventUuid,
                },
            })
        }

        return Promise.resolve(ok({ ingested }, acks, warnings))
    }
}

const SCALE_FACTOR = 16

type HeatmapDataItem = {
    x: number
    y: number
    target_fixed: boolean
    type: string
}

type HeatmapData = Record<string, HeatmapDataItem[]>

function replacePathInUrl(url: string, newPath: string): string {
    const parsedUrl = new URL(url)
    parsedUrl.pathname = newPath
    return parsedUrl.toString()
}

function isValidString(x: unknown): x is string {
    return typeof x === 'string' && !!x.trim().length
}

function isValidNumber(n: unknown): n is number {
    return typeof n === 'number' && !isNaN(n)
}

function isValidBoolean(b: unknown): b is boolean {
    return typeof b === 'boolean'
}

function extractScrollDepthHeatmapData(
    event: PreIngestionEvent
): PipelineResult<{ heatmapEvents: RawClickhouseHeatmapEvent[]; warnings: PipelineWarning[] }> {
    const warnings: PipelineWarning[] = []

    const { teamId, timestamp, properties, distinctId } = event
    const {
        $viewport_height,
        $viewport_width,
        $session_id,
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

    const heatmapEvents: RawClickhouseHeatmapEvent[] = []

    if (!heatmapData || Object.entries(heatmapData).length === 0) {
        return ok({ heatmapEvents: [], warnings })
    }

    if (!isValidString(distinctId) || isDistinctIdIllegal(distinctId)) {
        return drop('heatmap_invalid_distinct_id')
    }

    if (!isValidNumber($viewport_height) || !isValidNumber($viewport_width)) {
        logger.warn('👀', '[extract-heatmap-data] dropping because invalid viewport dimensions', {
            parent: event.event,
            teamId: teamId,
            eventTimestamp: timestamp,
            $viewport_height,
            $viewport_width,
        })
        return drop('heatmap_invalid_viewport_dimensions')
    }

    const eventTimestamp = castTimestampOrNow(timestamp ?? null, TimestampFormat.ClickHouse)
    const sessionIdStr = String($session_id)
    const scaledViewportHeight = Math.round($viewport_height / SCALE_FACTOR)
    const scaledViewportWidth = Math.round($viewport_width / SCALE_FACTOR)

    for (const [url, items] of Object.entries(heatmapData)) {
        if (!isValidString(url)) {
            warnings.push({
                type: 'rejecting_heatmap_data_with_invalid_url',
                details: {
                    heatmapUrl: url,
                    session_id: $session_id,
                },
                key: $session_id,
            })
            continue
        }

        if (!Array.isArray(items)) {
            warnings.push({
                type: 'rejecting_heatmap_data_with_invalid_items',
                details: {
                    heatmapUrl: url,
                    session_id: $session_id,
                },
                key: $session_id,
            })
            continue
        }

        const urlStr = String(url)
        for (const hme of items as any[]) {
            if (
                !isValidNumber(hme.x) ||
                !isValidNumber(hme.y) ||
                !isValidString(hme.type) ||
                !isValidBoolean(hme.target_fixed)
            ) {
                // TODO really we should add an ingestion warning here, but no urgency
                continue
            }

            heatmapEvents.push({
                type: hme.type,
                x: Math.round(hme.x / SCALE_FACTOR),
                y: Math.round(hme.y / SCALE_FACTOR),
                pointer_target_fixed: hme.target_fixed,
                viewport_height: scaledViewportHeight,
                viewport_width: scaledViewportWidth,
                current_url: urlStr,
                session_id: sessionIdStr,
                scale_factor: SCALE_FACTOR,
                timestamp: eventTimestamp,
                team_id: teamId,
                distinct_id: distinctId,
            })
        }
    }

    return ok({ heatmapEvents, warnings })
}
