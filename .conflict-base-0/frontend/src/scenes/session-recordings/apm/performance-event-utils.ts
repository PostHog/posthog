import { CapturedNetworkRequest } from 'posthog-js'

import { eventWithTime } from '@posthog/rrweb-types'

import { getSeriesBackgroundColor, getSeriesColor } from 'lib/colors'
import { humanizeBytes } from 'lib/utils'

import { PerformanceEvent } from '~/types'

const NETWORK_PLUGIN_NAME = 'posthog/network@1'
const RRWEB_NETWORK_PLUGIN_NAME = 'rrweb/network@1'

export const PerformanceEventReverseMapping: { [key: number]: keyof PerformanceEvent } = {
    // BASE_PERFORMANCE_EVENT_COLUMNS
    0: 'entry_type',
    1: 'time_origin',
    2: 'name',

    // RESOURCE_EVENT_COLUMNS
    3: 'start_time',
    4: 'redirect_start',
    5: 'redirect_end',
    6: 'worker_start',
    7: 'fetch_start',
    8: 'domain_lookup_start',
    9: 'domain_lookup_end',
    10: 'connect_start',
    11: 'secure_connection_start',
    12: 'connect_end',
    13: 'request_start',
    14: 'response_start',
    15: 'response_end',
    16: 'decoded_body_size',
    17: 'encoded_body_size',
    18: 'initiator_type',
    19: 'next_hop_protocol',
    20: 'render_blocking_status',
    21: 'response_status',
    22: 'transfer_size',

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    23: 'largest_contentful_paint_element',
    24: 'largest_contentful_paint_render_time',
    25: 'largest_contentful_paint_load_time',
    26: 'largest_contentful_paint_size',
    27: 'largest_contentful_paint_id',
    28: 'largest_contentful_paint_url',

    // NAVIGATION_EVENT_COLUMNS
    29: 'dom_complete',
    30: 'dom_content_loaded_event',
    31: 'dom_interactive',
    32: 'load_event_end',
    33: 'load_event_start',
    34: 'redirect_count',
    35: 'navigation_type',
    36: 'unload_event_end',
    37: 'unload_event_start',

    // Added after v1
    39: 'duration',
    40: 'timestamp',
}

export const RRWebPerformanceEventReverseMapping: Record<string, keyof PerformanceEvent> = {
    // BASE_PERFORMANCE_EVENT_COLUMNS
    entryType: 'entry_type',
    timeOrigin: 'time_origin',
    name: 'name',

    // RESOURCE_EVENT_COLUMNS
    startTime: 'start_time',
    redirectStart: 'redirect_start',
    redirectEnd: 'redirect_end',
    workerStart: 'worker_start',
    fetchStart: 'fetch_start',
    domainLookupStart: 'domain_lookup_start',
    domainLookupEnd: 'domain_lookup_end',
    connectStart: 'connect_start',
    secureConnectionStart: 'secure_connection_start',
    connectEnd: 'connect_end',
    requestStart: 'request_start',
    responseStart: 'response_start',
    responseEnd: 'response_end',
    decodedBodySize: 'decoded_body_size',
    encodedBodySize: 'encoded_body_size',
    initiatorType: 'initiator_type',
    nextHopProtocol: 'next_hop_protocol',
    renderBlockingStatus: 'render_blocking_status',

    // responseStatus if we receive the status via the performance observer
    responseStatus: 'response_status',
    // status if we receive it from wrapping fetch/xhr
    // we prefer status if we receive both
    status: 'response_status',

    transferSize: 'transfer_size',

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    largestContentfulPaintElement: 'largest_contentful_paint_element',
    largestContentfulPaintRenderTime: 'largest_contentful_paint_render_time',
    largestContentfulPaintLoadTime: 'largest_contentful_paint_load_time',
    largestContentfulPaintSize: 'largest_contentful_paint_size',
    largestContentfulPaintId: 'largest_contentful_paint_id',
    largestContentfulPaintUrl: 'largest_contentful_paint_url',

    // NAVIGATION_EVENT_COLUMNS
    domComplete: 'dom_complete',
    domContentLoadedEvent: 'dom_content_loaded_event',
    domInteractive: 'dom_interactive',
    loadEventEnd: 'load_event_end',
    loadEventStart: 'load_event_start',
    redirectCount: 'redirect_count',
    navigationType: 'navigation_type',
    unloadEventEnd: 'unload_event_end',
    unloadEventStart: 'unload_event_start',

    // Added after v1
    duration: 'duration',
    timestamp: 'timestamp',

    //rrweb/network@1
    isInitial: 'is_initial',
    requestHeaders: 'request_headers',
    responseHeaders: 'response_headers',
    requestBody: 'request_body',
    responseBody: 'response_body',
    method: 'method',
    endTime: 'end_time',
}

export function initiatorTypeToColor(type: NonNullable<PerformanceEvent['initiator_type']>): string {
    switch (type) {
        case 'navigation':
            return getSeriesColor(13)
        case 'css':
            return getSeriesColor(14)
        case 'script':
            return getSeriesColor(15)
        case 'xmlhttprequest':
            return getSeriesColor(16)
        case 'fetch':
            return getSeriesColor(17)
        case 'beacon':
            return getSeriesColor(18)
        case 'video':
            return getSeriesColor(19)
        case 'audio':
            return getSeriesColor(20)
        case 'track':
            return getSeriesColor(21)
        case 'img':
            return getSeriesColor(22)
        case 'image':
            return getSeriesColor(22)
        case 'input':
            return getSeriesColor(23)
        case 'a':
            return getSeriesColor(24)
        case 'iframe':
            return getSeriesColor(25)
        case 'frame':
            return getSeriesColor(26)
        case 'link':
            return getSeriesColor(27)
        case 'other':
            return getSeriesColor(28)
    }
}

type AssetType = 'CSS' | 'JS' | 'Fetch' | 'Image' | 'Link' | 'XHR' | 'HTML'

export const initiatorToAssetTypeMapping: Record<string, AssetType> = {
    css: 'CSS',
    script: 'JS',
    fetch: 'Fetch',
    img: 'Image',
    link: 'Link',
    xmlhttprequest: 'XHR',
    navigation: 'HTML',
}

// these map to colors in initiatorTypeToColor but with opacity
export function assetTypeToColor(type: AssetType): string {
    switch (type) {
        case 'CSS':
            return getSeriesBackgroundColor(14)
        case 'JS':
            return getSeriesBackgroundColor(15)
        case 'Fetch':
            return getSeriesBackgroundColor(17)
        case 'Image':
            return getSeriesBackgroundColor(22)
        case 'Link':
            return getSeriesBackgroundColor(27)
        case 'XHR':
            return getSeriesBackgroundColor(16)
        case 'HTML':
            return getSeriesBackgroundColor(13)
    }
}

export function mapRRWebNetworkRequest(
    capturedRequest: CapturedNetworkRequest,
    windowId: string,
    timestamp: PerformanceEvent['timestamp']
): PerformanceEvent {
    const data: Partial<PerformanceEvent> = {
        timestamp: timestamp,
        window_id: windowId,
        raw: capturedRequest,
    }

    Object.entries(RRWebPerformanceEventReverseMapping).forEach(([key, value]) => {
        if (key in capturedRequest) {
            data[value] = capturedRequest[key]
        }
    })

    // KLUDGE: this shouldn't be necessary but let's display correctly while we figure out why it is.
    if (!data.name && 'url' in capturedRequest) {
        data.name = capturedRequest.url as string | undefined
    }

    return data as PerformanceEvent
}

export function getPerformanceEvents(snapshotsByWindowId: Record<string, eventWithTime[]>): PerformanceEvent[] {
    // we only support rrweb/network@1 events or posthog/network@1 events in any one recording
    // apart from during testing, where we might have both
    // if we have both, we only display posthog/network@1 events
    const events: PerformanceEvent[] = []
    const rrwebEvents: PerformanceEvent[] = []

    Object.entries(snapshotsByWindowId).forEach(([windowId, snapshots]) => {
        snapshots.forEach((snapshot: eventWithTime) => {
            if (
                snapshot.type === 6 && // RRWeb plugin event type
                snapshot.data.plugin === NETWORK_PLUGIN_NAME
            ) {
                const properties = snapshot.data.payload as any

                const data: Partial<PerformanceEvent> = {
                    timestamp: snapshot.timestamp,
                    window_id: windowId,
                    raw: properties,
                }

                Object.entries(PerformanceEventReverseMapping).forEach(([key, value]) => {
                    if (key in properties) {
                        data[value] = properties[key]
                    }
                })

                events.push(data as PerformanceEvent)
            }

            if (
                snapshot.type === 6 && // RRWeb plugin event type
                snapshot.data.plugin === RRWEB_NETWORK_PLUGIN_NAME
            ) {
                const payload = snapshot.data.payload as any

                if (!Array.isArray(payload.requests) || payload.requests.length === 0) {
                    return
                }

                const serverTimings: Record<string, PerformanceEvent[]> = {}

                const perfEvents = payload.requests.map((capturedRequest: CapturedNetworkRequest) => {
                    return mapRRWebNetworkRequest(capturedRequest, windowId, snapshot.timestamp)
                })

                // first find all server timings and store them by timestamp
                perfEvents.forEach((perfEvent: PerformanceEvent) => {
                    if (perfEvent.entry_type === 'serverTiming') {
                        if (perfEvent.timestamp in serverTimings) {
                            serverTimings[perfEvent.timestamp].push(perfEvent)
                        } else {
                            serverTimings[perfEvent.timestamp] = [perfEvent]
                        }
                    }
                })

                // so we can match them to their parent events
                perfEvents.forEach((data: PerformanceEvent) => {
                    if (data.entry_type === 'serverTiming') {
                        return
                    }

                    if (data.timestamp in serverTimings) {
                        data.server_timings = serverTimings[data.timestamp]
                        delete serverTimings[data.timestamp]
                    }

                    rrwebEvents.push(data)
                })
            }
        })
    })

    return events.length ? events : rrwebEvents
}

function isPositiveNumber(value: any): value is number {
    return typeof value === 'number' && value >= 0
}

function bytesFrom(item: PerformanceEvent): number | null {
    // encoded body + header
    if (isPositiveNumber(item.transfer_size)) {
        return item.transfer_size
    }
    // body while encoded e.g. gzipped
    if (isPositiveNumber(item.encoded_body_size)) {
        return item.encoded_body_size
    }
    // body after being decoded e.g. unzipped
    if (isPositiveNumber(item.decoded_body_size)) {
        return item.decoded_body_size
    }

    if (item.response_body && typeof item.response_body === 'string') {
        const bodySize = new Blob([item.response_body]).size
        const headerSize = new Blob([JSON.stringify(item.response_headers)]).size
        return bodySize + headerSize
    }

    // we use null as the default not 0 because 0 can mean "was cached" and if we have no data we don't know
    return null
}

export interface PerformanceEventSizeInfo {
    formattedBytes: string
    compressionPercentage: number | null
    formattedDecodedBodySize: string | null
    formattedEncodedBodySize: string | null
    formattedCompressionPercentage: string | null
    isFromLocalCache: boolean
    bytes: number | null
    decodedBodySize: number | null
    encodedBodySize: number | null
}

export function itemSizeInfo(item: PerformanceEvent): PerformanceEventSizeInfo {
    const bytes = bytesFrom(item)
    const formattedBytes = humanizeBytes(bytes)
    const decodedBodySize = isPositiveNumber(item.decoded_body_size) ? item.decoded_body_size : null
    const formattedDecodedBodySize = isPositiveNumber(decodedBodySize) ? humanizeBytes(decodedBodySize) : null
    const encodedBodySize = isPositiveNumber(item.encoded_body_size) ? item.encoded_body_size : null
    const formattedEncodedBodySize = isPositiveNumber(encodedBodySize) ? humanizeBytes(encodedBodySize) : null
    const compressionPercentage =
        isPositiveNumber(item.decoded_body_size) && isPositiveNumber(item.encoded_body_size)
            ? ((item.decoded_body_size - item.encoded_body_size) / item.decoded_body_size) * 100
            : null
    const formattedCompressionPercentage = isPositiveNumber(compressionPercentage)
        ? `${compressionPercentage.toFixed(1)}%`
        : null
    const isFromLocalCache = item.transfer_size === 0 && (item.decoded_body_size || 0) > 0
    return {
        bytes,
        formattedBytes,
        compressionPercentage,
        decodedBodySize,
        formattedDecodedBodySize,
        encodedBodySize,
        formattedEncodedBodySize,
        formattedCompressionPercentage,
        isFromLocalCache,
    }
}
