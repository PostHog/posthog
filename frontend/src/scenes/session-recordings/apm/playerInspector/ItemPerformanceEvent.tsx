import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { LemonDivider, LemonTabs, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { Dayjs, dayjs } from 'lib/dayjs'
import { humanFriendlyMilliseconds } from 'lib/utils/durations'
import { isKeyOf } from 'lib/utils/guards'
import { isURL } from 'lib/utils/url'
import {
    isAutoRedactedBody,
    itemSizeInfo,
    PerformanceEventSizeInfo,
    unreadableBodyExplanation,
} from 'scenes/session-recordings/apm/performance-event-utils'
import { NavigationItem } from 'scenes/session-recordings/player/inspector/components/NavigationItem'
import { PerformanceEventLabel } from 'scenes/session-recordings/player/inspector/components/PerformanceEventLabel'
import { NetworkRequestTiming } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Body, PerformanceEvent } from '~/types'

const FriendlyHttpStatus = {
    0: 'Request not sent',
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    306: 'Unused',
    307: 'Temporary Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Required',
    413: 'Request Entry Too Large',
    414: 'Request-URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Requested Range Not Satisfiable',
    417: 'Expectation Failed',
    418: "I'm a teapot",
    429: 'Too Many Requests',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
} as const

export interface ItemPerformanceEventProps {
    item: PerformanceEvent
    finalTimestamp: Dayjs | null
}

function renderTimeBenchmark(milliseconds: number | null): JSX.Element | null {
    return milliseconds === null ? null : (
        <span
            className={clsx('font-semibold', {
                'text-danger-dark': milliseconds >= 2000,
                'text-warning-dark': milliseconds >= 500 && milliseconds < 2000,
            })}
        >
            {humanFriendlyMilliseconds(milliseconds)}
        </span>
    )
}

function emptyPayloadMessage(
    payloadCaptureIsEnabled: boolean | undefined | null,
    item: PerformanceEvent,
    label: 'Request' | 'Response'
): JSX.Element | string {
    return payloadCaptureIsEnabled ? (
        item.is_initial ? (
            `${label} captured before PostHog was initialized`
        ) : (
            `No ${label.toLowerCase()} body captured`
        )
    ) : (
        <>
            Payload capture is disabled.{' '}
            <Link to={urls.settings('project-replay', 'replay-network')}>Enable it here</Link>
        </>
    )
}

function StartedAt({ item }: { item: PerformanceEvent }): JSX.Element | null {
    const friendlyMillis = humanFriendlyMilliseconds(item.start_time || item.fetch_start)
    return friendlyMillis ? (
        <>
            started at <b>{friendlyMillis}</b> and
        </>
    ) : null
}

export function hasNoRecordedResponse(item: PerformanceEvent): boolean {
    // A captured fetch/XHR (method present) that recorded no response. Skip navigations and
    // requests captured before PostHog started. A fetch that throws records no status, while a
    // successful opaque cross-origin fetch records 0, so for fetch only an absent status means
    // no response. An XHR cannot be opaque, so it reports status 0 when it recorded none.
    //
    // The cause is not knowable from here: a firewall block, CORS, and a network error look the
    // same as an abort, and aborts are routine in an app that cancels in-flight requests. So this
    // reports only that no response was recorded, and never calls the request failed.
    return (
        item.entry_type !== 'navigation' &&
        !item.is_initial &&
        item.method !== undefined &&
        (item.response_status === undefined || (item.response_status === 0 && item.initiator_type === 'xmlhttprequest'))
    )
}

function durationMillisecondsFrom(item: PerformanceEvent): number | null {
    let duration = item.duration
    if (duration === undefined && item.end_time !== undefined && item.start_time !== undefined) {
        duration = item.end_time - item.start_time
    }
    return duration ?? null
}

function DurationDescription({ item }: { item: PerformanceEvent }): JSX.Element | null {
    const duration = durationMillisecondsFrom(item)
    if (duration === null) {
        return null
    }

    return (
        <>
            took <b>{humanFriendlyMilliseconds(duration)}</b>
        </>
    )
}

function SizeDescription({ sizeInfo }: { sizeInfo: PerformanceEventSizeInfo }): JSX.Element | null {
    return (
        <>
            {sizeInfo.formattedDecodedBodySize || sizeInfo.formattedBytes ? (
                <>
                    {' '}
                    to load <b>{sizeInfo.formattedDecodedBodySize || sizeInfo.formattedBytes}</b> of data
                </>
            ) : null}
            {sizeInfo.isFromLocalCache ? (
                <>
                    {' '}
                    <span className="text-secondary">(from local cache)</span>
                </>
            ) : null}
            {sizeInfo.formattedCompressionPercentage &&
            (sizeInfo.compressionPercentage || 0) > 0 &&
            sizeInfo.formattedEncodedBodySize ? (
                <>
                    , compressed to <b>{sizeInfo.formattedEncodedBodySize}</b> saving{' '}
                    <b>{sizeInfo.formattedCompressionPercentage}</b>
                </>
            ) : null}
        </>
    )
}

export function ItemPerformanceEvent({ item, finalTimestamp }: ItemPerformanceEventProps): JSX.Element {
    const sizeInfo = itemSizeInfo(item)

    const startTime = item.start_time || item.fetch_start || 0
    const duration = durationMillisecondsFrom(item)

    const callerOrigin = isURL(item.current_url) ? new URL(item.current_url).origin : undefined
    const eventName = item.name || '(empty string)'

    const shortEventName =
        callerOrigin && eventName.startsWith(callerOrigin) ? eventName.replace(callerOrigin, '') : eventName

    const contextLengthMs = finalTimestamp?.diff(dayjs(item.time_origin), 'ms') || 1000

    const {
        timestamp,
        uuid,
        name,
        session_id,
        pageview_id,
        distinct_id,
        time_origin,
        entry_type,
        current_url,
        ...otherProps
    } = item

    return (
        <div data-attr="item-performance-event" className="font-light w-full">
            <div className="flex-1 overflow-hidden">
                <div
                    className="absolute bg-accent rounded-xs opacity-75 h-1 bottom-0.5"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: `${(startTime / contextLengthMs) * 100}%`,
                        width: `${Math.max(((duration ?? 0) / contextLengthMs) * 100, 0.5)}%`,
                    }}
                />
                {item.entry_type === 'navigation' ? (
                    <NavigationItem item={item} expanded={false} navigationURL={shortEventName} />
                ) : (
                    <div className="flex gap-2 p-2 text-xs cursor-pointer items-center">
                        <MethodTag item={item} />
                        <PerformanceEventLabel name={item.name} expanded={false} />
                        {/* Highlight the request when it returned an error status, or when no
                            response was recorded for it at all */}
                        {otherProps.response_status && otherProps.response_status >= 400 ? (
                            <span
                                className={clsx(
                                    'font-semibold',
                                    otherProps.response_status < 500 ? 'text-warning-dark' : 'text-danger-dark'
                                )}
                            >
                                {otherProps.response_status}
                            </span>
                        ) : hasNoRecordedResponse(item) ? (
                            <span className="font-semibold text-warning-dark">no response</span>
                        ) : null}
                        {renderTimeBenchmark(duration)}
                        <span className={clsx('font-semibold')}>{sizeInfo.formattedBytes || 'size not available'}</span>
                    </div>
                )}
            </div>
        </div>
    )
}

export function ItemPerformanceEventDetail({ item }: ItemPerformanceEventProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<'timings' | 'headers' | 'payload' | 'response_body' | 'raw'>('timings')

    const { currentTeam } = useValues(teamLogic)
    const payloadCaptureIsEnabled =
        currentTeam?.capture_performance_opt_in &&
        currentTeam?.session_recording_network_payload_capture_config?.recordBody

    const sizeInfo = itemSizeInfo(item)

    const {
        timestamp,
        uuid,
        name,
        session_id,
        pageview_id,
        distinct_id,
        time_origin,
        entry_type,
        current_url,
        ...otherProps
    } = item

    // NOTE: This is a bit of a quick-fix for the fact that each event has all values despite most not applying.
    // We should probably do a specific mapping depending on the event type to display it properly (and probably give an info indicator what it all means...)

    const sanitizedProps = Object.entries(otherProps).reduce(
        (acc, [key, value]) => {
            if (value === 0 || value === '') {
                return acc
            }

            if (
                [
                    'response_headers',
                    'request_headers',
                    'request_body',
                    'response_body',
                    'response_status',
                    'raw',
                    'server_timings',
                ].includes(key)
            ) {
                return acc
            }

            if (key.includes('time') || key.includes('end') || key.includes('start')) {
                return acc
            }

            acc[key] = typeof value === 'number' ? Math.round(value) : value
            return acc
        },
        {} as Record<string, any>
    )

    return (
        <div className="p-2 text-xs border-t font-light w-full">
            <>
                <StatusRow item={item} />
                <p>
                    Request <StartedAt item={item} /> <DurationDescription item={item} />
                    <SizeDescription sizeInfo={sizeInfo} />.
                </p>
            </>
            <LemonDivider dashed />

            <LemonTabs
                size="small"
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                tabs={[
                    {
                        key: 'timings',
                        label: 'Timings',
                        content: (
                            <>
                                <SimpleKeyValueList item={sanitizedProps} />
                                <LemonDivider dashed />
                                <NetworkRequestTiming performanceEvent={item} />
                            </>
                        ),
                    },
                    item.request_headers || item.response_headers
                        ? {
                              key: 'headers',
                              label: 'Headers',
                              content: (
                                  <HeadersDisplay
                                      request={item.request_headers}
                                      response={item.response_headers}
                                      isInitial={item.is_initial}
                                  />
                              ),
                          }
                        : false,
                    item.entry_type !== 'navigation' &&
                    // if we're missing the initiator type, but we do have a body then we should show it
                    (['fetch', 'xmlhttprequest'].includes(item.initiator_type || '') || !!item.request_body)
                        ? {
                              key: 'payload',
                              label: 'Payload',
                              content: (
                                  <BodyDisplay
                                      content={item.request_body}
                                      headers={item.request_headers}
                                      emptyMessage={emptyPayloadMessage(payloadCaptureIsEnabled, item, 'Request')}
                                  />
                              ),
                          }
                        : false,
                    item.entry_type !== 'navigation' && item.response_body
                        ? {
                              key: 'response_body',
                              label: 'Response',
                              content: (
                                  <BodyDisplay
                                      content={item.response_body}
                                      headers={item.response_headers}
                                      emptyMessage={emptyPayloadMessage(payloadCaptureIsEnabled, item, 'Response')}
                                  />
                              ),
                          }
                        : false,
                    {
                        key: 'raw',
                        label: 'Json',
                        content: (
                            <CodeSnippet language={Language.JSON} wrap thing="performance event">
                                {JSON.stringify(item.raw || 'no item to display', null, 2)}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
        </div>
    )
}

export function BodyDisplay({
    content,
    headers,
    emptyMessage,
}: {
    content: Body | undefined
    headers: Record<string, string> | undefined
    emptyMessage?: string | JSX.Element | null
}): JSX.Element | null {
    if (content == null) {
        return <>{emptyMessage}</>
    }
    const headerContentType = headers?.['content-type']

    let language = Language.Text
    let displayContent = content
    if (typeof displayContent !== 'string') {
        displayContent = JSON.stringify(displayContent, null, 2)
    } else if (displayContent.trim() === '') {
        displayContent = '(empty string)'
    }
    if (headerContentType === 'application/json') {
        language = Language.JSON
    }

    const bodyDiagnostic = unreadableBodyExplanation(displayContent)
    if (bodyDiagnostic) {
        return (
            <>
                <p>{bodyDiagnostic}</p>
                <pre>received: {displayContent}</pre>
            </>
        )
    }

    return isAutoRedactedBody(displayContent) ? (
        <>
            <p>
                This content was redacted by PostHog to protect sensitive data.{' '}
                <Link
                    to="https://posthog.com/docs/session-replay/network-recording?utm_medium=in-product"
                    target="_blank"
                >
                    Learn how to override PostHog's automatic redaction code.
                </Link>
            </p>
            <pre>received: {displayContent}</pre>
        </>
    ) : (
        <CodeSnippet language={language} wrap={true} thing="request body" compact={false}>
            {displayContent}
        </CodeSnippet>
    )
}

export function HeadersDisplay({
    request,
    response,
    isInitial,
}: {
    request: Record<string, string> | undefined
    response: Record<string, string> | undefined
    isInitial?: boolean
}): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const isHeadersCaptureEnabled =
        currentTeam?.capture_performance_opt_in &&
        currentTeam?.session_recording_network_payload_capture_config?.recordHeaders
    const emptyMessage = isInitial ? 'captured before PostHog was initialized' : 'No headers captured'

    return (
        <div className="flex flex-col w-full">
            {isHeadersCaptureEnabled ? (
                <>
                    <div>
                        <h4 className="font-semibold">Request Headers</h4>
                        <SimpleKeyValueList item={request || {}} emptyMessage={emptyMessage} />
                    </div>
                    <LemonDivider dashed />
                    <div>
                        <h4 className="font-semibold">Response Headers</h4>
                        <SimpleKeyValueList item={response || {}} emptyMessage={emptyMessage} />
                    </div>
                </>
            ) : (
                <>
                    Headers capture is disabled.{' '}
                    <Link to={urls.settings('project-replay', 'replay-network')}>Enable it here</Link>
                </>
            )}
        </div>
    )
}

export function StatusTag({ item, detailed }: { item: PerformanceEvent; detailed: boolean }): JSX.Element | null {
    const { response_status: responseStatus, transfer_size: transferSize, response_body: responseBody } = item

    if (hasNoRecordedResponse(item)) {
        // Render this here so every renderer that shares StatusTag marks it, including the
        // network waterfall, not just the inspector list.
        return (
            <div className="flex gap-4 items-center justify-between overflow-hidden">
                {detailed ? <div className="font-semibold">Status code</div> : null}
                <div>
                    <LemonTag type="warning">No response</LemonTag>
                    {detailed ? (
                        <span className="text-secondary"> the request was blocked, failed, or cancelled</span>
                    ) : null}
                </div>
            </div>
        )
    }

    if (responseStatus === undefined) {
        return null
    }

    let fromDiskCache = false
    if (transferSize === 0 && responseBody && responseStatus && responseStatus < 400) {
        fromDiskCache = true
    }

    const statusDescription = `${responseStatus} ${isKeyOf(responseStatus, FriendlyHttpStatus) ? FriendlyHttpStatus[responseStatus] : ''}`

    let statusType: LemonTagType = 'success'
    if (responseStatus >= 500) {
        statusType = 'danger'
    } else if (responseStatus >= 400 || responseStatus < 100) {
        statusType = 'warning'
    }

    return (
        <div className="flex gap-4 items-center justify-between overflow-hidden">
            {detailed ? <div className="font-semibold">Status code</div> : null}
            <div>
                <LemonTag type={statusType}>{statusDescription}</LemonTag>
                {detailed && fromDiskCache ? <span className="text-secondary"> (from cache)</span> : null}
            </div>
        </div>
    )
}

export function MethodTag({ item, label }: { item: PerformanceEvent; label?: boolean }): JSX.Element | null {
    if (item.method === undefined) {
        return null
    }
    return (
        <div className="flex gap-4 items-center justify-between overflow-hidden">
            {label ? <div className="font-semibold">Request method</div> : null}
            <div className="uppercase font-semibold">{item.method}</div>
        </div>
    )
}

function StatusRow({ item }: { item: PerformanceEvent }): JSX.Element | null {
    let statusRow = null
    let methodRow = null

    if (item.response_status || hasNoRecordedResponse(item)) {
        statusRow = <StatusTag item={item} detailed={true} />
    }

    if (item.method) {
        methodRow = <MethodTag item={item} label={true} />
    }

    return methodRow || statusRow ? (
        <p>
            <div className="text-xs deprecated-space-y-1 max-w-full">
                {methodRow}
                {statusRow}
            </div>
            <LemonDivider dashed />
        </p>
    ) : null
}
