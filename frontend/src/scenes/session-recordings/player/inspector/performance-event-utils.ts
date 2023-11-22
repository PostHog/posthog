import { eventWithTime } from '@rrweb/types'
import { CapturedNetworkRequest } from 'posthog-js'

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
    responseStatus: 'response_status',
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

export function matchNetworkEvents(snapshotsByWindowId: Record<string, eventWithTime[]>): PerformanceEvent[] {
    // we only support rrweb/network@1 events or posthog/network@1 events in any one recording
    // apart from during testing, where we might have both
    // if we have both, we only display posthog/network@1 events
    const events: PerformanceEvent[] = []
    const rrwebEvents: PerformanceEvent[] = []

    // we could do this in one pass, but it's easier to log missing events
    // when we have all the posthog/network@1 events first

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

                payload.requests.forEach((capturedRequest: any) => {
                    const data: PerformanceEvent = mapRRWebNetworkRequest(capturedRequest, windowId, snapshot.timestamp)

                    rrwebEvents.push(data)
                })
            }
        })
    })

    return events.length ? events : rrwebEvents
}
