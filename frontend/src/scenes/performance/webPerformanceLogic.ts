import { kea } from 'kea'
import { EventType } from '~/types'

import { getChartColors } from 'lib/colors'

import { webPerformanceLogicType } from './webPerformanceLogicType'
import { urls } from 'scenes/urls'
import { router } from 'kea-router'
import api from 'lib/api'

export enum WebPerformancePage {
    TABLE = 'table',
    WATERFALL_CHART = 'waterfall_chart',
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
    if (!entries || !entries.length) {
        return []
    }
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

const maybeIncrementMaxTime = (maxTime: number, candidate: number): number =>
    candidate > maxTime ? candidate : maxTime

/**
 * There are defined sections to performance measurement. We may have data for some or all of them
 *
 * 1) Redirect
 *  - from startTime which would also be redirectStart
 *  - until redirectEnd
 *
 *  2) App Cache
 *   - from fetchStart
 *   - until domainLookupStart
 *
 *  3) DNS
 *   - from domainLookupStart
 *   - until domainLookupEnd
 *
 *  4) TCP
 *   - from connectStart
 *   - until connectEnd
 *
 *   this contains any time to negotiate SSL/TLS
 *   - from secureConnectionStart
 *   - until connectEnd
 *
 *  5) Request
 *   - from requestStart
 *   - until responseStart
 *
 *  6) Response
 *   - from responseStart
 *   - until responseEnd
 *
 *  7) Document Processing
 *   - from responseEnd
 *   - until loadEventEnd
 *
 * see https://nicj.net/resourcetiming-in-practice/
 *
 * @param perfEntry
 * @param maxTime
 */
function calculatePerformanceParts(
    perfEntry: PerformanceResourceTiming | PerformanceNavigationTiming,
    maxTime: number
): {
    performanceParts: Record<string, EventPerformanceMeasure>
    maxTime: number
} {
    const performanceParts: Record<string, EventPerformanceMeasure> = {}

    if (perfEntry.redirectStart && perfEntry.redirectEnd) {
        performanceParts['redirect'] = {
            start: perfEntry.redirectStart,
            end: perfEntry.redirectEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.redirectEnd)
    }

    if (perfEntry.fetchStart && perfEntry.domainLookupStart) {
        performanceParts['app cache'] = {
            start: perfEntry.fetchStart,
            end: perfEntry.domainLookupStart,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.redirectEnd)
    }

    if (perfEntry.domainLookupEnd && perfEntry.domainLookupStart) {
        performanceParts['dns lookup'] = {
            start: perfEntry.domainLookupStart,
            end: perfEntry.domainLookupEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.domainLookupEnd)
    }

    if (perfEntry.connectEnd && perfEntry.connectStart) {
        performanceParts['connection time'] = {
            start: perfEntry.connectStart,
            end: perfEntry.connectEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }

        if (perfEntry.secureConnectionStart) {
            performanceParts['tls time'] = {
                start: perfEntry.secureConnectionStart,
                end: perfEntry.connectEnd,
                color: colorForEntry(perfEntry.initiatorType),
                reducedHeight: true,
            }
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.connectEnd)
    }

    if (perfEntry.responseStart && perfEntry.requestStart) {
        performanceParts['waiting for first byte (TTFB)'] = {
            start: perfEntry.requestStart,
            end: perfEntry.responseStart,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.responseStart)
    }

    if (perfEntry.responseStart && perfEntry.responseEnd) {
        performanceParts['receiving response'] = {
            start: perfEntry.responseStart,
            end: perfEntry.responseEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, perfEntry.responseEnd)
    }

    if (perfEntry.responseEnd && (perfEntry as PerformanceNavigationTiming).loadEventEnd) {
        performanceParts['document processing'] = {
            start: perfEntry.responseEnd,
            end: (perfEntry as PerformanceNavigationTiming).loadEventEnd,
            color: colorForEntry(perfEntry.initiatorType),
        }
        maxTime = maybeIncrementMaxTime(maxTime, (perfEntry as PerformanceNavigationTiming).loadEventEnd)
    }

    return { performanceParts, maxTime }
}

function forWaterfallDisplay(pageViewEvent: EventType): EventPerformanceData {
    console.log(pageViewEvent, 'loading event')
    const perfData = decompress(JSON.parse(pageViewEvent.properties.$performance_raw))
    const navTiming: PerformanceNavigationTiming = perfData.navigation[0]
    let maxTime = 0

    const pointsInTime = {}
    if (navTiming?.domComplete) {
        pointsInTime['domComplete'] = { time: navTiming.domComplete, color: colorForEntry('domComplete') }
    }
    if (navTiming?.domInteractive) {
        pointsInTime['domInteractive'] = { time: navTiming.domInteractive, color: colorForEntry('domInteractive') }
    }

    if (navTiming?.duration) {
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
    resourceTimings.push({ item: new URL(navTiming.name), performanceParts: __ret.performanceParts, entry: navTiming })
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

export const webPerformanceLogic = kea<webPerformanceLogicType<EventPerformanceData, WebPerformancePage>>({
    path: ['scenes', 'performance'],
    actions: {
        setEventToDisplay: (eventToDisplay: EventType) => ({
            eventToDisplay,
        }),
        clearEventToDisplay: true,
        setCurrentPage: (page: WebPerformancePage) => ({ page }),
    },
    reducers: {
        eventToDisplay: [
            null as EventPerformanceData | null,
            {
                setEventToDisplay: (_, { eventToDisplay }) => forWaterfallDisplay(eventToDisplay),
                clearEventToDisplay: () => null,
            },
        ],
        currentEvent: [null as EventType | null, { setEventToDisplay: (_, { eventToDisplay }) => eventToDisplay }],
        currentPage: [WebPerformancePage.TABLE, { setCurrentPage: (_, { page }) => page }],
    },
    loaders: {
        event: {
            loadEvent: async (id: string | number) => {
                return api.events.get(id)
            },
        },
    },
    listeners: ({ actions }) => ({
        loadEventSuccess: ({ event }) => {
            actions.setEventToDisplay(event)
        },
    }),
    actionToUrl: ({ values }) => ({
        setEventToDisplay: () => {
            if (values.currentPage === WebPerformancePage.TABLE && !!values.currentEvent) {
                //then we're navigating to the chart
                return [
                    urls.webPerformanceWaterfall(values.currentEvent.id.toString()),
                    {
                        ...router.values.searchParams,
                    },
                    router.values.hashParams,
                ]
            }

            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    }),
    urlToAction: ({ values, actions }) => ({
        [urls.webPerformance()]: () => {
            console.log('matched top route')
            if (values.currentPage !== WebPerformancePage.TABLE) {
                actions.setCurrentPage(WebPerformancePage.TABLE)
            }
        },
        [urls.webPerformanceWaterfall(':id')]: ({ id }) => {
            console.log('matched id route')
            if (values.currentPage !== WebPerformancePage.WATERFALL_CHART) {
                actions.setCurrentPage(WebPerformancePage.WATERFALL_CHART)
            }
            if (values.currentEvent === null && !!id) {
                actions.loadEvent(id)
            }
        },
    }),
})
