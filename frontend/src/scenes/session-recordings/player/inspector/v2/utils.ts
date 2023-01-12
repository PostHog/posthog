import { PerformanceEvent } from '~/types'

// Creates a single performance summary event. Assumes events parameters only contains one navigation event.
export function createPerformanceSummaryFromNavigation(
    events: PerformanceEvent[],
    startIndex: number,
    endIndex: number
): PerformanceEvent {
    const navigationEvent = events[startIndex]
    const pageEvents = events.slice(startIndex, endIndex)
    const fcpIndex = pageEvents.findIndex(({ name }) => name === 'first-contentful-paint')

    if (fcpIndex === -1) {
        return {
            ...navigationEvent,
            uuid: `performance-summary-event-${navigationEvent.uuid}`,
            entry_type: 'performance-summary',
            first_contentful_paint: undefined,
            time_to_interactive: undefined,
            total_blocking_time: undefined,
        }
    }

    /*
     * TTI calculation: https://web.dev/tti/#what-is-tti
     *  1. start at FCP
     *  2. Search forward in time for a quiet window of at least five seconds, where quiet window is defined as: no long tasks and no more than two in-flight network GET requests.
     *  3. Search backwards for the last long task before the quiet window, stopping at FCP if no long tasks are found.
     *  4. TTI is the end time of the last long task before the quiet window (or the same value as FCP if no long tasks are found).
     */
    let ttiIndex = fcpIndex
    let firstIdleIndex = pageEvents.length

    for (let i = fcpIndex + 1; i < pageEvents.length; i++) {
        const event = pageEvents[i]
        const prevEvent = pageEvents[i - 1]
        if (!event.start_time || !prevEvent.response_end) {
            continue
        }
        if (event.start_time - prevEvent.response_end > 5000) {
            firstIdleIndex = i
            break
        }
    }

    for (let i = firstIdleIndex - 1; i > fcpIndex; i--) {
        const event = pageEvents[i]
        if (!event.duration) {
            continue
        }
        if (event.duration > 50) {
            ttiIndex = i
            break
        }
    }

    /*
     * TBT calculation: https://web.dev/tbt/#what-is-tbt
     * 1. Add up all durations exceeding 50ms between FCP and TTI
     */
    let tbt_duration = 0
    for (let i = fcpIndex; i < Math.min(ttiIndex + 1, pageEvents.length); i++) {
        const event = pageEvents[i]
        if (!event.duration) {
            continue
        }
        const total_blocking_time = Math.max(event.duration - 50, 0)
        tbt_duration += total_blocking_time
    }

    return {
        ...navigationEvent,
        uuid: `performance-summary-event-${navigationEvent.uuid}`,
        entry_type: 'performance-summary',
        first_contentful_paint: pageEvents[fcpIndex].start_time,
        time_to_interactive: pageEvents[ttiIndex].response_end,
        total_blocking_time: tbt_duration,
    }
}

export function createPerformanceSummaryEvents(events: PerformanceEvent[]): PerformanceEvent[] {
    // There may be multiple navigation events in a single recording, so we create a performance summary for each navigation event.

    const navigationIndices = []
    for (let i = 0; i < events.length; i++) {
        if (events[i].entry_type === 'navigation') {
            navigationIndices.push(i)
        }
    }

    if (navigationIndices.length === 0) {
        return events
    }

    navigationIndices.push(events.length) // to help with looping with an offset
    let finalEvents = events.slice(0, navigationIndices[0])
    for (let i = 0; i < navigationIndices.length - 1; i++) {
        const prevNavI = navigationIndices[i]
        const nextNavI = navigationIndices[i + 1]
        const performanceSummaryEvent = createPerformanceSummaryFromNavigation(events, prevNavI, nextNavI)
        finalEvents = [...finalEvents, performanceSummaryEvent, ...events.slice(prevNavI, nextNavI)]
    }
    return finalEvents
}

export const IMAGE_WEB_EXTENSIONS = [
    'png',
    'jpg',
    'jpeg',
    'gif',
    'tif',
    'tiff',
    'gif',
    'svg',
    'webp',
    'bmp',
    'ico',
    'cur',
]
