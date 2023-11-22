import { getSeriesColor } from 'lib/colors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyMilliseconds } from 'lib/utils'
import { useState } from 'react'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { PerformanceEvent } from '~/types'

export interface EventPerformanceMeasure {
    start: number
    end: number
    color: string
    reducedHeight?: boolean
}

const perfSections = [
    'redirect',
    'app cache',
    'dns lookup',
    'connection time',
    'tls time',
    'request queuing time',
    'waiting for first byte',
    'receiving response',
    'document processing',
] as const

const perfDescriptions: Record<(typeof perfSections)[number], string> = {
    redirect:
        'The time it took to fetch any previous resources that redirected to this one. If either redirect_start or redirect_end timestamp is 0, there were no redirects, or one of the redirects wasn’t from the same origin as this resource.',
    'app cache': 'The time taken to check the application cache or fetch the resource from the application cache.',
    'dns lookup': 'The time taken to complete any DNS lookup for the resource.',
    'connection time': 'The time taken to establish a connection to the server to retrieve the resource.',
    'tls time': 'The time taken for the SSL/TLS handshake.',
    'request queuing time': "The time taken waiting in the browser's task queue once ready to make a request.",
    'waiting for first byte':
        'The time taken waiting for the server to start returning a response. Also known as TTFB or time to first byte.',
    'receiving response': 'The time taken to receive the response from the server.',
    'document processing':
        'The time taken to process the document after the response from the server has been received.',
}

function colorForSection(section: (typeof perfSections)[number]): string {
    switch (section) {
        case 'redirect':
            return getSeriesColor(2)
        case 'app cache':
            return getSeriesColor(3)
        case 'dns lookup':
            return getSeriesColor(4)
        case 'connection time':
            return getSeriesColor(5)
        case 'tls time':
            return getSeriesColor(6)
        case 'request queuing time':
            return getSeriesColor(7)
        case 'waiting for first byte':
            return getSeriesColor(8)
        case 'receiving response':
            return getSeriesColor(9)
        case 'document processing':
            return getSeriesColor(10)
        default:
            return getSeriesColor(11)
    }
}

type PerformanceMeasures = Record<string, EventPerformanceMeasure>

/**
 * There are defined sections to performance measurement. We may have data for some or all of them
 *
 *
 * 0) Queueing
 * - from start_time
 * - until the first item with activity
 *
 * 1) Redirect
 *  - from startTime which would also be redirectStart
 *  - until redirect_end
 *
 *  2) App Cache
 *   - from fetch_start
 *   - until domain_lookup_start
 *
 *  3) DNS
 *   - from domain_lookup_start
 *   - until domain_lookup_end
 *
 *  4) TCP
 *   - from connect_start
 *   - until connect_end
 *
 *   this contains any time to negotiate SSL/TLS
 *   - from secure_connection_start
 *   - until connect_end
 *
 *  5) Request
 *   - from request_start
 *   - until response_start
 *
 *  6) Response
 *   - from response_start
 *   - until response_end
 *
 *  7) Document Processing
 *   - from response_end
 *   - until load_event_end
 *
 * see https://nicj.net/resourcetiming-in-practice/
 */
export function calculatePerformanceParts(perfEntry: PerformanceEvent): PerformanceMeasures {
    const performanceParts: Record<string, EventPerformanceMeasure> = {}

    if (isPresent(perfEntry.redirect_start) && isPresent(perfEntry.redirect_end)) {
        if (perfEntry.redirect_end - perfEntry.redirect_start > 0) {
            performanceParts['redirect'] = {
                start: perfEntry.redirect_start,
                end: perfEntry.redirect_end,
                color: colorForSection('redirect'),
            }
        }
    }

    if (isPresent(perfEntry.fetch_start) && isPresent(perfEntry.domain_lookup_start)) {
        if (perfEntry.domain_lookup_start - perfEntry.fetch_start > 0) {
            performanceParts['app cache'] = {
                start: perfEntry.fetch_start,
                end: perfEntry.domain_lookup_start,
                color: colorForSection('app cache'),
            }
        }
    }

    if (isPresent(perfEntry.domain_lookup_end) && isPresent(perfEntry.domain_lookup_start)) {
        if (perfEntry.domain_lookup_end - perfEntry.domain_lookup_start > 0) {
            performanceParts['dns lookup'] = {
                start: perfEntry.domain_lookup_start,
                end: perfEntry.domain_lookup_end,
                color: colorForSection('dns lookup'),
            }
        }
    }

    if (isPresent(perfEntry.connect_end) && isPresent(perfEntry.connect_start)) {
        if (perfEntry.connect_end - perfEntry.connect_start > 0) {
            performanceParts['connection time'] = {
                start: perfEntry.connect_start,
                end: perfEntry.connect_end,
                color: colorForSection('connection time'),
            }

            if (isPresent(perfEntry.secure_connection_start) && perfEntry.secure_connection_start > 0) {
                performanceParts['tls time'] = {
                    start: perfEntry.secure_connection_start,
                    end: perfEntry.connect_end,
                    color: colorForSection('tls time'),
                    reducedHeight: true,
                }
            }
        }
    }

    if (
        isPresent(perfEntry.connect_end) &&
        isPresent(perfEntry.request_start) &&
        perfEntry.connect_end !== perfEntry.request_start
    ) {
        if (perfEntry.request_start - perfEntry.connect_end > 0) {
            performanceParts['request queuing time'] = {
                start: perfEntry.connect_end,
                end: perfEntry.request_start,
                color: colorForSection('request queuing time'),
            }
        }
    }

    if (isPresent(perfEntry.response_start) && isPresent(perfEntry.request_start)) {
        if (perfEntry.response_start - perfEntry.request_start > 0) {
            performanceParts['waiting for first byte'] = {
                start: perfEntry.request_start,
                end: perfEntry.response_start,
                color: colorForSection('waiting for first byte'),
            }
        }
    }

    if (isPresent(perfEntry.response_start) && isPresent(perfEntry.response_end)) {
        if (perfEntry.response_end - perfEntry.response_start > 0) {
            // if loading from disk cache then response_start is 0 but fetch_start is not
            let start = perfEntry.response_start
            if (perfEntry.response_start === 0 && isPresent(perfEntry.fetch_start)) {
                start = perfEntry.fetch_start
            }
            performanceParts['receiving response'] = {
                start: start,
                end: perfEntry.response_end,
                color: colorForSection('receiving response'),
            }
        }
    }

    if (isPresent(perfEntry.response_end) && isPresent(perfEntry.load_event_end)) {
        if (perfEntry.load_event_end - perfEntry.response_end > 0) {
            performanceParts['document processing'] = {
                start: perfEntry.response_end,
                end: perfEntry.load_event_end,
                color: colorForSection('document processing'),
            }
        }
    }

    return performanceParts
}

function percentage(partDuration: number, totalDuration: number, min: number): number {
    return Math.min(Math.max(min, (partDuration / totalDuration) * 100), 100)
}

function percentagesWithinEventRange({
    partStart,
    partEnd,
    rangeEnd,
    rangeStart,
}: {
    partStart: number
    partEnd: number
    rangeStart: number
    rangeEnd: number
}): { startPercentage: string; widthPercentage: string } {
    const totalDuration = rangeEnd - rangeStart
    const partStartRelativeToTimeline = partStart - rangeStart
    const partDuration = partEnd - partStart

    const partPercentage = percentage(partDuration, totalDuration, 0.1)
    const partStartPercentage = percentage(partStartRelativeToTimeline, totalDuration, 0)
    return { startPercentage: `${partStartPercentage}%`, widthPercentage: `${partPercentage}%` }
}

const TimeLineView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element | null => {
    const rangeStart = performanceEvent.start_time
    const rangeEnd = performanceEvent.load_event_end ? performanceEvent.load_event_end : performanceEvent.response_end
    if (typeof rangeStart === 'number' && typeof rangeEnd === 'number') {
        const timings = calculatePerformanceParts(performanceEvent)
        return (
            <div className={'font-semibold text-xs'}>
                {perfSections.map((section) => {
                    const matchedSection = timings[section]
                    const start = matchedSection?.start
                    const end = matchedSection?.end
                    const partDuration = end - start
                    let formattedDuration: string | undefined
                    let startPercentage = null
                    let widthPercentage = null

                    if (isNaN(partDuration) || partDuration === 0) {
                        formattedDuration = ''
                    } else {
                        formattedDuration = humanFriendlyMilliseconds(partDuration)
                        const percentages = percentagesWithinEventRange({
                            rangeStart,
                            rangeEnd,
                            partStart: start,
                            partEnd: end,
                        })
                        startPercentage = percentages.startPercentage
                        widthPercentage = percentages.widthPercentage
                    }

                    return (
                        <>
                            <div key={section} className={'flex flex-row px-2 py-1'}>
                                <div className={'w-2/5'}>
                                    <Tooltip title={perfDescriptions[section]}>{section}</Tooltip>
                                </div>
                                <div className={'flex-1 grow relative'}>
                                    <div
                                        className={'relative h-full'}
                                        /* eslint-disable-next-line react/forbid-dom-props */
                                        style={{
                                            backgroundColor: colorForSection(section),
                                            width: widthPercentage ?? '0%',
                                            left: startPercentage ?? '0%',
                                        }}
                                    />
                                </div>
                                <div className={'w-1/6 text-right'}>{formattedDuration || ''}</div>
                            </div>
                        </>
                    )
                })}
            </div>
        )
    }
    return null
}

const TableView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element => {
    const timingProperties = Object.entries(performanceEvent).reduce((acc, [key, val]) => {
        if (key.includes('time') || key.includes('end') || key.includes('start')) {
            acc[key] = val
        }
        return acc
    }, {})
    return <SimpleKeyValueList item={timingProperties} />
}

export const NetworkRequestTiming = ({
    performanceEvent,
}: {
    performanceEvent: PerformanceEvent
}): JSX.Element | null => {
    const [timelineMode, setTimelineMode] = useState<boolean>(true)

    // if timeline view renders null then we fall back to table view
    const timelineView = timelineMode ? <TimeLineView performanceEvent={performanceEvent} /> : null

    return (
        <div className={'flex flex-col space-y-2'}>
            <div className={'flex flex-row justify-end'}>
                <LemonButton
                    type={'secondary'}
                    size={'xsmall'}
                    status={'stealth'}
                    onClick={() => setTimelineMode(!timelineMode)}
                    data-attr={`switch-timing-to-${timelineMode ? 'table' : 'timeline'}-view`}
                >
                    {timelineMode ? 'Table view' : 'Timeline view'}
                </LemonButton>
            </div>
            <LemonDivider dashed={true} />
            {timelineMode && timelineView ? timelineView : <TableView performanceEvent={performanceEvent} />}
        </div>
    )
}

function isPresent(x: number | undefined): x is number {
    return typeof x === 'number'
}
