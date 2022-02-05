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

export interface EventPerformanceMeasure {
    start: number
    end: number
    color: string
    reducedHeight?: boolean
}

interface PointInTimeMarker {
    time: number
    color: string
}

export interface EventPerformanceData {
    id: string | number
    pointsInTime: Record<string, PointInTimeMarker>
    resourceTimings: ResourceTiming[]
    maxTime: number
    gridMarkers: number[]
}

function expandOptimisedEntries(entries: [string[], any[]]): Record<string, any>[] {
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
        return []
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

export interface MinimalPerformanceResourceTiming extends Omit<PerformanceEntry, 'entryType' | 'toJSON'> {
    name: string
    fetchStart: number
    responseEnd: number
}

export interface ResourceTiming {
    item: string | URL
    entry: MinimalPerformanceResourceTiming | PerformanceResourceTiming | PerformanceNavigationTiming
    performanceParts: Record<string, EventPerformanceMeasure>
    color?: string
}

function calculatePerformanceParts(
    perfEntry: PerformanceResourceTiming | PerformanceNavigationTiming,
    maxTime: number
): { performanceParts: Record<string, EventPerformanceMeasure>; maxTime: number } {
    const performanceParts: Record<string, EventPerformanceMeasure> = {}
    if (perfEntry.domainLookupEnd && perfEntry.domainLookupStart) {
        performanceParts['dns lookup'] = {
            start: perfEntry.domainLookupStart,
            end: perfEntry.domainLookupEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = perfEntry.domainLookupEnd > maxTime ? perfEntry.domainLookupEnd : maxTime
    }

    if (perfEntry.connectEnd && perfEntry.connectStart) {
        performanceParts['connection time'] = {
            start: perfEntry.connectStart,
            end: perfEntry.connectEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = perfEntry.connectEnd > maxTime ? perfEntry.connectEnd : maxTime
    }

    if (perfEntry.connectEnd && perfEntry.secureConnectionStart) {
        performanceParts['tls time'] = {
            start: perfEntry.secureConnectionStart,
            end: perfEntry.connectEnd,
            color: colorForEntry(perfEntry.initiatorType),
            reducedHeight: true,
        }
        maxTime = perfEntry.connectEnd > maxTime ? perfEntry.connectEnd : maxTime
    }

    if (perfEntry.responseStart && perfEntry.requestStart) {
        performanceParts['waiting for first byte (TTFB)'] = {
            start: perfEntry.requestStart,
            end: perfEntry.responseStart,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = perfEntry.responseStart > maxTime ? perfEntry.responseStart : maxTime
    }

    if (perfEntry.responseStart && perfEntry.responseEnd) {
        performanceParts['receiving response'] = {
            start: perfEntry.responseStart,
            end: perfEntry.responseEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = perfEntry.responseEnd > maxTime ? perfEntry.responseEnd : maxTime
    }

    if (perfEntry.responseEnd && (perfEntry as PerformanceNavigationTiming).loadEventEnd) {
        performanceParts['document processing'] = {
            start: perfEntry.responseEnd,
            end: (perfEntry as PerformanceNavigationTiming).loadEventEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime =
            (perfEntry as PerformanceNavigationTiming).loadEventEnd > maxTime
                ? (perfEntry as PerformanceNavigationTiming).loadEventEnd
                : maxTime
    }

    return { performanceParts, maxTime }
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

    const resourceTimings: ResourceTiming[] = []

    const __ret = calculatePerformanceParts(navTiming, maxTime)
    resourceTimings.push({ item: 'the page', performanceParts: __ret.performanceParts, entry: navTiming })
    maxTime = __ret.maxTime

    perfData.resource.forEach((resource: PerformanceResourceTiming) => {
        const resourceURL = new URL(resource.name)
        const performanceCalculations = calculatePerformanceParts(resource, maxTime)
        const next = {
            item: resourceURL,
            performanceParts: performanceCalculations.performanceParts,
            entry: resource,
            color: colorForEntry(resource.initiatorType),
        }

        resourceTimings.push(next)
        maxTime = resource.responseEnd > maxTime ? resource.responseEnd : maxTime
    })

    return {
        id: pageViewEvent.id,
        pointsInTime,
        resourceTimings,
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
