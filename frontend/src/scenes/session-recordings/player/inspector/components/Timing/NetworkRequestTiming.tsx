import { PerformanceEvent } from '~/types'
import { getSeriesColor } from 'lib/colors'
import { humanFriendlyMilliseconds } from 'lib/utils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState } from 'react'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

function colorForEntry(entryType: string | undefined): string {
    switch (entryType) {
        case 'domComplete':
            return getSeriesColor(1)
        case 'domInteractive':
            return getSeriesColor(2)
        case 'pageLoaded':
            return getSeriesColor(3)
        case 'first-contentful-paint':
            return getSeriesColor(4)
        case 'css':
            return getSeriesColor(6)
        case 'xmlhttprequest':
            return getSeriesColor(7)
        case 'fetch':
            return getSeriesColor(8)
        case 'other':
            return getSeriesColor(9)
        case 'script':
            return getSeriesColor(10)
        case 'link':
            return getSeriesColor(11)
        case 'first-paint':
            return getSeriesColor(11)
        default:
            return getSeriesColor(13)
    }
}

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
    'waiting for first byte (TTFB)',
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
    'waiting for first byte (TTFB)': 'The time taken waiting for the server to start returning a response.',
    'receiving response': 'The time taken to receive the response from the server.',
    'document processing':
        'The time taken to process the document after the response from the server has been received.',
}

function colorForSection(section: (typeof perfSections)[number]): string {
    switch (section) {
        case 'redirect':
            return getSeriesColor(1)
        case 'app cache':
            return getSeriesColor(2)
        case 'dns lookup':
            return getSeriesColor(3)
        case 'connection time':
            return getSeriesColor(4)
        case 'tls time':
            return getSeriesColor(6)
        case 'waiting for first byte (TTFB)':
            return getSeriesColor(7)
        case 'receiving response':
            return getSeriesColor(8)
        case 'document processing':
            return getSeriesColor(9)
        default:
            return getSeriesColor(10)
    }
}

/**
 * There are defined sections to performance measurement. We may have data for some or all of them
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
 *
 * @param perfEntry
 * @param maxTime
 */
function calculatePerformanceParts(perfEntry: PerformanceEvent): Record<string, EventPerformanceMeasure> {
    const performanceParts: Record<string, EventPerformanceMeasure> = {}

    if (perfEntry.redirect_start && perfEntry.redirect_end) {
        performanceParts['redirect'] = {
            start: perfEntry.redirect_start,
            end: perfEntry.redirect_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    if (perfEntry.fetch_start && perfEntry.domain_lookup_start) {
        performanceParts['app cache'] = {
            start: perfEntry.fetch_start,
            end: perfEntry.domain_lookup_start,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    if (perfEntry.domain_lookup_end && perfEntry.domain_lookup_start) {
        performanceParts['dns lookup'] = {
            start: perfEntry.domain_lookup_start,
            end: perfEntry.domain_lookup_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    if (perfEntry.connect_end && perfEntry.connect_start) {
        performanceParts['connection time'] = {
            start: perfEntry.connect_start,
            end: perfEntry.connect_end,
            color: colorForEntry(perfEntry.initiator_type),
        }

        if (perfEntry.secure_connection_start) {
            performanceParts['tls time'] = {
                start: perfEntry.secure_connection_start,
                end: perfEntry.connect_end,
                color: colorForEntry(perfEntry.initiator_type),
                reducedHeight: true,
            }
        }
    }

    if (perfEntry.response_start && perfEntry.request_start) {
        performanceParts['waiting for first byte (TTFB)'] = {
            start: perfEntry.request_start,
            end: perfEntry.response_start,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    if (perfEntry.response_start && perfEntry.response_end) {
        performanceParts['receiving response'] = {
            start: perfEntry.response_start,
            end: perfEntry.response_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    if (perfEntry.response_end && perfEntry.load_event_end) {
        performanceParts['document processing'] = {
            start: perfEntry.response_end,
            end: perfEntry.load_event_end,
            color: colorForEntry(perfEntry.initiator_type),
        }
    }

    return performanceParts
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

    const partPercentage = (partDuration / totalDuration) * 100
    const partStartPercentage = (partStartRelativeToTimeline / totalDuration) * 100
    return { startPercentage: `${partStartPercentage}%`, widthPercentage: `${partPercentage}%` }
}

const TimeLineView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element => {
    const rangeStart = performanceEvent.start_time
    const rangeEnd = performanceEvent.response_end
    if (typeof rangeStart === 'number' && typeof rangeEnd === 'number') {
        const performanceParts = calculatePerformanceParts(performanceEvent)
        return (
            <div className={'font-semibold text-xs'}>
                {perfSections.map((section) => {
                    const matchedSection = performanceParts[section]
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
    return <LemonBanner type={'warning'}>Cannot render performance timeline for this request</LemonBanner>
}

const TableView = ({ performanceEvent }: { performanceEvent: PerformanceEvent }): JSX.Element => {
    const timingProperties = Object.entries(performanceEvent).reduce((acc, [key, val]) => {
        if (['_start', '_end', '_time'].some((suffix) => key.endsWith(suffix))) {
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

    return (
        <div className={'flex flex-col space-y-2'}>
            <div className={'flex flex-row justify-end'}>
                <LemonButton
                    type={'secondary'}
                    status={'stealth'}
                    onClick={() => setTimelineMode(!timelineMode)}
                    data-attr={`switch-timing-to-${timelineMode ? 'table' : 'timeline'}-view`}
                >
                    {timelineMode ? 'table view' : 'timeline view'}
                </LemonButton>
            </div>
            <LemonDivider dashed={true} />
            {timelineMode ? (
                <TimeLineView performanceEvent={performanceEvent} />
            ) : (
                <TableView performanceEvent={performanceEvent} />
            )}
        </div>
    )
}
