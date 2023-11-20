import { eventWithTime } from '@rrweb/types'
import posthog from 'posthog-js'
import { PerformanceEvent } from '~/types'

const NETWORK_PLUGIN_NAME = 'posthog/network@1'
const RRWEB_NETWORK_PLUGIN_NAME = 'rrweb/network@1'
const IGNORED_POSTHOG_PATHS = ['/s/', '/e/', '/i/v0/e/']

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

export function matchNetworkEvents(snapshotsByWindowId: Record<string, eventWithTime[]>): PerformanceEvent[] {
    const eventsMapping: Record<string, Record<number, PerformanceEvent[]>> = {}

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

                // not all performance events have a URL, e.g. some are page events
                // but, even so, they should have a name and a start time
                const mappedData = data as PerformanceEvent

                const startTime = Math.round(mappedData.start_time === undefined ? -1 : mappedData.start_time)
                // we expect the event to always have a name... but we also don't completely trust the internet
                const eventName = mappedData.name || 'unknown'

                eventsMapping[eventName] = eventsMapping[eventName] || {}
                eventsMapping[eventName][startTime] = eventsMapping[eventName][startTime] || []
                eventsMapping[eventName][startTime].push(mappedData)
            }
        })
    })

    // now we have all the posthog/network@1 events we can try to match any rrweb/network@1 events
    Object.entries(snapshotsByWindowId).forEach((snapshotsByWindowId) => {
        const snapshots = snapshotsByWindowId[1]
        snapshots.forEach((snapshot: eventWithTime) => {
            if (
                snapshot.type === 6 && // RRWeb plugin event type
                snapshot.data.plugin === RRWEB_NETWORK_PLUGIN_NAME
            ) {
                const payload = snapshot.data.payload as any
                if (!Array.isArray(payload.requests) || payload.requests.length === 0) {
                    return
                }

                payload.requests.forEach((capturedRequest: any) => {
                    const matchedURL = eventsMapping[capturedRequest.url]

                    const matchedStartTime = matchedURL ? matchedURL[capturedRequest.startTime] : null

                    if (matchedStartTime && matchedStartTime.length === 1) {
                        matchedStartTime[0].response_status = capturedRequest.status
                        matchedStartTime[0].request_headers = capturedRequest.requestHeaders
                        matchedStartTime[0].request_body = capturedRequest.requestBody
                        matchedStartTime[0].response_headers = capturedRequest.responseHeaders
                        matchedStartTime[0].response_body = capturedRequest.responseBody
                        matchedStartTime[0].method = capturedRequest.method
                    } else if (matchedStartTime && matchedStartTime.length > 1) {
                        // find in eventsMapping[capturedRequest.url][capturedRequest.startTime] by matching capturedRequest.endTime and element.response_end
                        const matchedEndTime = matchedStartTime.find(
                            (x) =>
                                typeof x.response_end === 'number' &&
                                Math.round(x.response_end) === capturedRequest.endTime
                        )
                        if (matchedEndTime) {
                            matchedEndTime.response_status = capturedRequest.status
                            matchedEndTime.request_headers = capturedRequest.requestHeaders
                            matchedEndTime.request_body = capturedRequest.requestBody
                            matchedEndTime.response_headers = capturedRequest.responseHeaders
                            matchedEndTime.response_body = capturedRequest.responseBody
                            matchedEndTime.method = capturedRequest.method
                        } else {
                            const capturedURL = new URL(capturedRequest.url)
                            const capturedPath = capturedURL.pathname

                            if (!IGNORED_POSTHOG_PATHS.some((x) => capturedPath === x)) {
                                posthog.capture('Had matches but still could not match rrweb/network@1 event', {
                                    rrwebNetworkEvent: payload,
                                    possibleMatches: matchedStartTime,
                                    totalMatchedURLs: Object.keys(eventsMapping).length,
                                })
                            }
                        }
                    } else {
                        const capturedURL = new URL(capturedRequest.url)
                        const capturedPath = capturedURL.pathname
                        if (!IGNORED_POSTHOG_PATHS.some((x) => capturedPath === x)) {
                            posthog.capture('Could not match rrweb/network@1 event', {
                                rrwebNetworkEvent: payload,
                                possibleMatches: eventsMapping[capturedRequest.url],
                                totalMatchedURLs: Object.keys(eventsMapping).length,
                            })
                        }
                    }
                })
            }
        })
    })

    // now flatten the eventsMapping into a single array
    return Object.values(eventsMapping).reduce((acc: PerformanceEvent[], eventsByURL) => {
        Object.values(eventsByURL).forEach((eventsByTime) => {
            acc.push(...eventsByTime)
        })
        return acc
    }, [])
}
