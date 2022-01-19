import { kea } from 'kea'
import { EventType, FilterType, PropertyOperator } from '~/types'
import api from 'lib/api'

import { getChartColors } from 'lib/colors'

import { webPerformanceLogicType } from './webPerformanceLogicType'
const eventApiProps: Partial<FilterType> = {
    properties: [
        { key: '$performance_page_loaded', value: '0', operator: PropertyOperator.GreaterThan, type: 'event' },
        { key: '$performance_raw', value: 'is_set', operator: PropertyOperator.IsSet, type: 'event' },
    ],
}

interface EventPerformanceMeasure {
    start: number
    end: number
    color: string
}

interface PointInTimeMarker {
    time: number
    color: string
}

export interface EventPerformanceData {
    id: string | number
    pointsInTime: Record<string, PointInTimeMarker>
    durations: Record<string, EventPerformanceMeasure>
    maxTime: number
    gridMarkers: number[]
}

function expandOptimisedEntries(entries: [string[], any[]]): Record<string, any> {
    try {
        const keys = entries[0]
        return entries[1].map((entry) => {
            return entry.reduce((acc: Record<string, any>, entryValue: any, index: number) => {
                acc[keys[index]] = entryValue
                return acc
            }, {})
        })
    } catch (e) {
        console.error({ e, entries }, 'could not decompress performance entries')
        return {}
    }
}

function decompress(
    compressedRawPerformanceData: Record<'navigation' | 'paint' | 'resource', [string[], any[]]>
): Record<string, any> {
    return {
        navigation: expandOptimisedEntries(compressedRawPerformanceData.navigation),
        paint: expandOptimisedEntries(compressedRawPerformanceData.paint),
        resource: expandOptimisedEntries(compressedRawPerformanceData.resource),
    }
}

const colors = getChartColors('green')
function colorForEntry(entryType: string): string {
    switch (entryType) {
        case 'domComplete':
            return colors[0]
        case 'domInteractive':
            return colors[2]
        case 'pageLoaded':
            return colors[3]
        case 'firstContentfulPaint':
            return colors[4]
        case 'css':
            return colors[6]
        case 'xmlhttprequest':
            return colors[7]
        case 'fetch':
            return colors[8]
        case 'other':
            return colors[9]
        case 'script':
            return colors[10]
        case 'link':
            return colors[11]
        default:
            return colors[13]
    }
}

function forWaterfallDisplay(pageViewEvent: EventType): EventPerformanceData {
    const perfData = decompress(JSON.parse(pageViewEvent.properties.$performance_raw))
    const navTiming: PerformanceNavigationTiming = perfData.navigation[0]
    let maxTime = 0

    const pointsInTime = {}
    if (navTiming.domComplete) {
        pointsInTime['domComplete'] = { time: navTiming.domComplete, color: colorForEntry('domComplete') }
    }
    if (navTiming.domInteractive) {
        pointsInTime['domInteractive'] = { time: navTiming.domInteractive, color: colorForEntry('domInteractive') }
    }

    if (navTiming.duration) {
        pointsInTime['pageLoaded'] = { time: navTiming.duration, color: colorForEntry('pageLoaded') }
        maxTime = navTiming.duration > maxTime ? navTiming.duration : maxTime
    }

    const paintTimings: PerformanceEntryList = perfData.paint || ([] as PerformanceEntryList)
    const fcp: PerformanceEntry | undefined = paintTimings.find(
        (p: PerformanceEntry) => p.name === 'first-contentful-paint'
    )
    if (fcp) {
        pointsInTime['firstContentfulPaint'] = { time: fcp.startTime, color: colorForEntry('firstContentfulPaint') }
        maxTime = fcp.startTime > maxTime ? fcp.startTime : maxTime
    }

    const durations: Record<string, EventPerformanceMeasure> = {}
    if (navTiming.domainLookupEnd && navTiming.domainLookupStart) {
        durations['dns lookup'] = {
            start: navTiming.domainLookupStart,
            end: navTiming.domainLookupEnd,
            color: colorForEntry(navTiming.initiatorType),
        }
        maxTime = navTiming.domainLookupEnd > maxTime ? navTiming.domainLookupEnd : maxTime
    }

    if (navTiming.connectEnd && navTiming.connectStart) {
        durations['connection time'] = {
            start: navTiming.connectStart,
            end: navTiming.connectEnd,
            color: colorForEntry(navTiming.initiatorType),
        }
        maxTime = navTiming.connectEnd > maxTime ? navTiming.connectEnd : maxTime
    }

    if (navTiming.connectEnd && navTiming.secureConnectionStart) {
        durations['tls time'] = {
            start: navTiming.secureConnectionStart,
            end: navTiming.connectEnd,
            color: colorForEntry(navTiming.initiatorType),
        }
        maxTime = navTiming.connectEnd > maxTime ? navTiming.connectEnd : maxTime
    }

    if (navTiming.responseStart && navTiming.requestStart) {
        durations['waiting for first byte (TTFB)'] = {
            start: navTiming.requestStart,
            end: navTiming.responseStart,
            color: colorForEntry(navTiming.initiatorType),
        }
        maxTime = navTiming.responseStart > maxTime ? navTiming.responseStart : maxTime
    }

    perfData.resource.forEach((resource: PerformanceResourceTiming) => {
        const resourceURL = new URL(resource.name)
        durations[resourceURL.pathname] = {
            start: resource.startTime,
            end: resource.responseEnd,
            color: colorForEntry(resource.initiatorType),
        }
        maxTime = resource.responseEnd > maxTime ? resource.responseEnd : maxTime
    })

    return {
        id: pageViewEvent.id,
        pointsInTime,
        durations: durations,
        maxTime,
        gridMarkers: Array.from(Array(10).keys()).map((n) => n * (maxTime / 10)),
    }
}

export const webPerformanceLogic = kea<webPerformanceLogicType<EventPerformanceData>>({
    path: ['scenes', 'performance'],
    actions: {
        setEventToDisplay: (eventToDisplay: EventType) => ({
            eventToDisplay,
        }),
    },
    reducers: {
        eventToDisplay: [
            null as EventPerformanceData | null,
            { setEventToDisplay: (_, { eventToDisplay }) => forWaterfallDisplay(eventToDisplay) },
        ],
        currentEvent: [null as EventType | null, { setEventToDisplay: (_, { eventToDisplay }) => eventToDisplay }],
    },
    loaders: () => ({
        pageViewEvents: {
            loadEvents: async () => {
                const loadResult = await api.events.list(eventApiProps, 10)
                return loadResult?.results || []
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadEvents],
    }),
})
