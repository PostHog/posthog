import { kea } from 'kea'
import { EventType, FilterType, PropertyOperator } from '~/types'
import api from 'lib/api'

import { apmLogicType } from './apmLogicType'
const eventApiProps: Partial<FilterType> = {
    properties: [{ key: '$performance_raw', value: 'is_set', operator: PropertyOperator.IsSet, type: 'event' }],
}

interface EventPerformanceMeasure {
    start: number
    end: number
}

export interface EventPerformanceData {
    id: string | number
    pointsInTime: Record<string, number>
    durations: Record<string, EventPerformanceMeasure>
    maxTime: number
    gridMarkers: number[]
}

function forWaterfallDisplay(pageViewEvent: EventType): EventPerformanceData {
    const perfData = JSON.parse(pageViewEvent.properties.$performance_raw)
    const navTiming: PerformanceNavigationTiming = perfData.navigation[0]
    let maxTime = 0

    const pointsInTime = {}
    if (navTiming.domComplete) {
        pointsInTime['domComplete'] = navTiming.domComplete
    }
    if (navTiming.domInteractive) {
        pointsInTime['domInteractive'] = navTiming.domInteractive
    }

    if (navTiming.duration) {
        pointsInTime['pageLoaded'] = navTiming.duration
        maxTime = navTiming.duration > maxTime ? navTiming.duration : maxTime
    }

    const durations: Record<string, EventPerformanceMeasure> = {}
    if (navTiming.domainLookupEnd && navTiming.domainLookupStart) {
        durations['dns lookup'] = { start: navTiming.domainLookupStart, end: navTiming.domainLookupEnd }
        maxTime = navTiming.domainLookupEnd > maxTime ? navTiming.domainLookupEnd : maxTime
    }

    if (navTiming.connectEnd && navTiming.connectStart) {
        durations['connection time'] = { start: navTiming.connectStart, end: navTiming.connectEnd }
        maxTime = navTiming.connectEnd > maxTime ? navTiming.connectEnd : maxTime
    }

    if (navTiming.connectEnd && navTiming.secureConnectionStart) {
        durations['tls time'] = { start: navTiming.secureConnectionStart, end: navTiming.connectEnd }
        maxTime = navTiming.connectEnd > maxTime ? navTiming.connectEnd : maxTime
    }

    if (navTiming.responseStart && navTiming.requestStart) {
        durations['waiting for first byte (TTFB)'] = { start: navTiming.requestStart, end: navTiming.responseStart }
        maxTime = navTiming.responseStart > maxTime ? navTiming.responseStart : maxTime
    }

    perfData.resource.forEach((resource: PerformanceResourceTiming) => {
        const resourceURL = new URL(resource.name)
        durations[resourceURL.pathname] = { start: resource.startTime, end: resource.responseEnd }
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

export const apmLogic = kea<apmLogicType<EventPerformanceData>>({
    path: ['scenes', 'apm'],
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
    },
    loaders: () => ({
        pageViewEvents: {
            loadEvents: async () => {
                const loadResult = await api.events.list(eventApiProps, 10)
                console.log(loadResult)
                return loadResult?.results || []
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadEvents],
    }),
})
