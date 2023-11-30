import { LemonButton, LemonDivider, LemonTabs, LemonTag, LemonTagType, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyMilliseconds, humanizeBytes, isURL } from 'lib/utils'
import { Fragment, useState } from 'react'
import { NetworkRequestTiming } from 'scenes/session-recordings/player/inspector/components/Timing/NetworkRequestTiming'

import { Body, PerformanceEvent } from '~/types'

import { SimpleKeyValueList } from './SimpleKeyValueList'

const friendlyHttpStatus = {
    '0': 'Request not sent',
    '200': 'OK',
    '201': 'Created',
    '202': 'Accepted',
    '203': 'Non-Authoritative Information',
    '204': 'No Content',
    '205': 'Reset Content',
    '206': 'Partial Content',
    '300': 'Multiple Choices',
    '301': 'Moved Permanently',
    '302': 'Found',
    '303': 'See Other',
    '304': 'Not Modified',
    '305': 'Use Proxy',
    '306': 'Unused',
    '307': 'Temporary Redirect',
    '400': 'Bad Request',
    '401': 'Unauthorized',
    '402': 'Payment Required',
    '403': 'Forbidden',
    '404': 'Not Found',
    '405': 'Method Not Allowed',
    '406': 'Not Acceptable',
    '407': 'Proxy Authentication Required',
    '408': 'Request Timeout',
    '409': 'Conflict',
    '410': 'Gone',
    '411': 'Length Required',
    '412': 'Precondition Required',
    '413': 'Request Entry Too Large',
    '414': 'Request-URI Too Long',
    '415': 'Unsupported Media Type',
    '416': 'Requested Range Not Satisfiable',
    '417': 'Expectation Failed',
    '418': "I'm a teapot",
    '429': 'Too Many Requests',
    '500': 'Internal Server Error',
    '501': 'Not Implemented',
    '502': 'Bad Gateway',
    '503': 'Service Unavailable',
    '504': 'Gateway Timeout',
    '505': 'HTTP Version Not Supported',
}

export interface ItemPerformanceEvent {
    item: PerformanceEvent
    expanded: boolean
    setExpanded: (expanded: boolean) => void
    finalTimestamp?: Dayjs
}

const performanceSummaryCards = [
    {
        label: 'First Contentful Paint',
        description: (
            <div>
                The First Contentful Paint (FCP) metric measures the time from when the page starts loading to when any
                part of the page's content is rendered on the screen.{' '}
                <Link
                    disableClientSideRouting
                    to="https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint"
                    target="_blank"
                >
                    Read more on developer.mozilla.org
                </Link>
            </div>
        ),
        key: 'first_contentful_paint',
        scoreBenchmarks: [1800, 3000],
    },
    {
        label: 'DOM Interactive',
        description: (
            <div>
                The document has finished loading and the document has been parsed but sub-resources such as scripts,
                images, stylesheets and frames are still loading.{' '}
                <Link
                    disableClientSideRouting
                    to="https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState"
                    target="_blank"
                >
                    Read more on developer.mozilla.org
                </Link>
            </div>
        ),
        key: 'dom_interactive',
        scoreBenchmarks: [3800, 7300],
    },
    {
        label: 'Page Loaded',
        description: (
            <div>
                The load event is fired when the whole page has loaded, including all dependent resources such as
                stylesheets and images. This is in contrast to DOMContentLoaded, which is fired as soon as the page DOM
                has been loaded, without waiting for resources to finish loading.{' '}
                <Link
                    disableClientSideRouting
                    to="https://developer.mozilla.org/en-US/docs/Web/API/Window/load_event"
                    target="_blank"
                >
                    Read more on developer.mozilla.org
                </Link>
            </div>
        ),
        key: 'load_event_end',
        scoreBenchmarks: [3800, 7300],
    },
]

function renderTimeBenchmark(milliseconds: number): JSX.Element {
    return (
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

function itemSizeInfo(item: PerformanceEvent): {
    bytes: string
    compressionPercentage: number | null
    decodedBodySize: string | null
    encodedBodySize: string | null
    formattedCompressionPercentage: string | null
    isFromLocalCache: boolean
} {
    const bytes = humanizeBytes(item.encoded_body_size || item.decoded_body_size || item.transfer_size || 0)
    const decodedBodySize = item.decoded_body_size ? humanizeBytes(item.decoded_body_size) : null
    const encodedBodySize = item.encoded_body_size ? humanizeBytes(item.encoded_body_size) : null
    const compressionPercentage =
        item.decoded_body_size && item.encoded_body_size
            ? ((item.decoded_body_size - item.encoded_body_size) / item.decoded_body_size) * 100
            : null
    const formattedCompressionPercentage = compressionPercentage ? `${compressionPercentage.toFixed(1)}%` : null
    const isFromLocalCache = item.transfer_size === 0 && (item.decoded_body_size || 0) > 0
    return {
        bytes,
        compressionPercentage,
        decodedBodySize,
        encodedBodySize,
        formattedCompressionPercentage,
        isFromLocalCache,
    }
}

export function ItemPerformanceEvent({
    item,
    finalTimestamp,
    expanded,
    setExpanded,
}: ItemPerformanceEvent): JSX.Element {
    const [activeTab, setActiveTab] = useState<'timings' | 'headers' | 'payload' | 'response_body' | 'raw'>('timings')

    const sizeInfo = itemSizeInfo(item)
    const startTime = item.start_time || item.fetch_start || 0
    const duration = item.duration || 0

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
        window_id,
        pageview_id,
        distinct_id,
        time_origin,
        entry_type,
        current_url,
        ...otherProps
    } = item

    // NOTE: This is a bit of a quick-fix for the fact that each event has all values despite most not applying.
    // We should probably do a specific mapping depending on the event type to display it properly (and probably give an info indicator what it all means...)

    const sanitizedProps = Object.entries(otherProps).reduce((acc, [key, value]) => {
        if (value === 0 || value === '') {
            return acc
        }

        if (
            ['response_headers', 'request_headers', 'request_body', 'response_body', 'response_status', 'raw'].includes(
                key
            )
        ) {
            return acc
        }

        if (key.includes('time') || key.includes('end') || key.includes('start')) {
            return acc
        }

        return {
            ...acc,
            [key]: typeof value === 'number' ? Math.round(value) : value,
        }
    }, {} as Record<string, any>)

    return (
        <div>
            <LemonButton
                noPadding
                onClick={() => setExpanded(!expanded)}
                status={'primary-alt'}
                fullWidth
                data-attr={'item-performance-event'}
            >
                <div className="flex-1 overflow-hidden">
                    <div
                        className="absolute bg-primary rounded-sm opacity-75"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            height: 4,
                            bottom: 2,
                            left: `${(startTime / contextLengthMs) * 100}%`,
                            width: `${Math.max((duration / contextLengthMs) * 100, 0.5)}%`,
                        }}
                    />
                    {item.entry_type === 'navigation' ? (
                        <NavigationItem item={item} expanded={expanded} shortEventName={shortEventName} />
                    ) : (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                                {shortEventName}
                            </span>
                            {/* We only show the status if it exists and is an error status */}
                            {otherProps.response_status && otherProps.response_status >= 400 ? (
                                <span
                                    className={clsx(
                                        'font-semibold',
                                        otherProps.response_status >= 400 &&
                                            otherProps.response_status < 500 &&
                                            'text-warning-dark',
                                        otherProps.response_status >= 500 && 'text-danger-dark'
                                    )}
                                >
                                    {otherProps.response_status}
                                </span>
                            ) : null}
                            {renderTimeBenchmark(duration)}
                            <span className={clsx('font-semibold')}>{sizeInfo.bytes}</span>
                        </div>
                    )}
                </div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    {item.name && (
                        <CodeSnippet language={Language.Markup} wrap thing="performance event name">
                            {item.name}
                        </CodeSnippet>
                    )}

                    {item.entry_type === 'navigation' ? (
                        <>
                            {performanceSummaryCards.map(({ label, description, key, scoreBenchmarks }) => (
                                <div key={key}>
                                    <div className="flex gap-2 font-semibold my-1">
                                        <span>{label}</span>
                                        <span>
                                            {item?.[key] === undefined ? (
                                                '-'
                                            ) : (
                                                <span
                                                    className={clsx({
                                                        'text-danger-dark': item[key] >= scoreBenchmarks[1],
                                                        'text-warning-dark':
                                                            item[key] >= scoreBenchmarks[0] &&
                                                            item[key] < scoreBenchmarks[1],
                                                    })}
                                                >
                                                    {humanFriendlyMilliseconds(item[key])}
                                                </span>
                                            )}
                                        </span>
                                    </div>

                                    <p>{description}</p>
                                </div>
                            ))}
                        </>
                    ) : (
                        <>
                            <FlaggedFeature flag={FEATURE_FLAGS.NETWORK_PAYLOAD_CAPTURE} match={true}>
                                <StatusRow item={item} />
                            </FlaggedFeature>
                            <p>
                                Request started at{' '}
                                <b>{humanFriendlyMilliseconds(item.start_time || item.fetch_start)}</b> and took{' '}
                                <b>{humanFriendlyMilliseconds(item.duration)}</b>
                                {sizeInfo.decodedBodySize ? (
                                    <>
                                        {' '}
                                        to load <b>{sizeInfo.decodedBodySize}</b> of data
                                    </>
                                ) : null}
                                {sizeInfo.isFromLocalCache ? (
                                    <>
                                        {' '}
                                        <span className={'text-muted'}>(from local cache)</span>
                                    </>
                                ) : null}
                                {sizeInfo.formattedCompressionPercentage && sizeInfo.encodedBodySize ? (
                                    <>
                                        , compressed to <b>{sizeInfo.encodedBodySize}</b> saving{' '}
                                        <b>{sizeInfo.formattedCompressionPercentage}</b>
                                    </>
                                ) : null}
                                .
                            </p>
                        </>
                    )}
                    <LemonDivider dashed />
                    {['fetch', 'xmlhttprequest'].includes(item.initiator_type || '') ? (
                        <>
                            <FlaggedFeature flag={FEATURE_FLAGS.NETWORK_PAYLOAD_CAPTURE} match={true}>
                                <LemonTabs
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
                                        {
                                            key: 'headers',
                                            label: 'Headers',
                                            content: (
                                                <HeadersDisplay
                                                    request={item.request_headers}
                                                    response={item.response_headers}
                                                />
                                            ),
                                        },
                                        item.entry_type !== 'navigation' && {
                                            key: 'payload',
                                            label: 'Payload',
                                            content: (
                                                <BodyDisplay
                                                    content={item.request_body}
                                                    headers={item.request_headers}
                                                    emptyMessage={'No request body captured'}
                                                />
                                            ),
                                        },
                                        item.entry_type !== 'navigation' && item.response_body
                                            ? {
                                                  key: 'response_body',
                                                  label: 'Response',
                                                  content: (
                                                      <BodyDisplay
                                                          content={item.response_body}
                                                          headers={item.response_headers}
                                                          emptyMessage={'No response body captured'}
                                                      />
                                                  ),
                                              }
                                            : false,
                                        // raw is only available if the feature flag is enabled
                                        // TODO before proper release we should put raw behind its own flag
                                        {
                                            key: 'raw',
                                            label: 'Json',
                                            content: (
                                                <CodeSnippet language={Language.JSON} wrap thing="performance event">
                                                    {JSON.stringify(item.raw, null, 2)}
                                                </CodeSnippet>
                                            ),
                                        },
                                    ]}
                                />
                            </FlaggedFeature>
                            <FlaggedFeature flag={FEATURE_FLAGS.NETWORK_PAYLOAD_CAPTURE} match={false}>
                                <SimpleKeyValueList item={sanitizedProps} />
                                <LemonDivider dashed />
                                <NetworkRequestTiming performanceEvent={item} />
                            </FlaggedFeature>
                        </>
                    ) : (
                        <>
                            <SimpleKeyValueList item={sanitizedProps} />
                            <LemonDivider dashed />
                            <NetworkRequestTiming performanceEvent={item} />
                        </>
                    )}
                </div>
            )}
        </div>
    )
}

function BodyDisplay({
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
    }
    if (headerContentType === 'application/json') {
        language = Language.JSON
    }

    return (
        <CodeSnippet language={language} wrap={true} thing="request body" compact={false}>
            {displayContent}
        </CodeSnippet>
    )
}

function HeadersDisplay({
    request,
    response,
}: {
    request: Record<string, string> | undefined
    response: Record<string, string> | undefined
}): JSX.Element | null {
    return (
        <div className="flex flex-col w-full">
            <div>
                <h4 className="font-semibold">Request Headers</h4>
                <SimpleKeyValueList item={request || {}} emptyMessage={'No headers captured'} />
            </div>
            <LemonDivider dashed />
            <div>
                <h4 className="font-semibold">Response Headers</h4>
                <SimpleKeyValueList item={response || {}} emptyMessage={'No headers captured'} />
            </div>
        </div>
    )
}

function StatusRow({ item }: { item: PerformanceEvent }): JSX.Element | null {
    let statusRow = null
    let methodRow = null

    let fromDiskCache = false
    if (item.transfer_size === 0 && item.response_body && item.response_status && item.response_status < 400) {
        fromDiskCache = true
    }

    if (item.response_status) {
        const statusDescription = `${item.response_status} ${friendlyHttpStatus[item.response_status] || ''}`

        let statusType: LemonTagType = 'success'
        if (item.response_status >= 400 || item.response_status < 100) {
            statusType = 'warning'
        } else if (item.response_status >= 500) {
            statusType = 'danger'
        }

        statusRow = (
            <div className="flex gap-4 items-center justify-between overflow-hidden">
                <div className="font-semibold">Status code</div>
                <div>
                    <LemonTag type={statusType}>{statusDescription}</LemonTag>
                    {fromDiskCache && <span className={'text-muted'}> (from cache)</span>}
                </div>
            </div>
        )
    }

    if (item.method) {
        methodRow = (
            <div className="flex gap-4 items-center justify-between overflow-hidden">
                <div className="font-semibold">Request method</div>
                <div className={'uppercase font-semibold'}>{item.method}</div>
            </div>
        )
    }

    return methodRow || statusRow ? (
        <p>
            <div className="text-xs space-y-1 max-w-full">
                {methodRow}
                {statusRow}
            </div>
            <LemonDivider dashed />
        </p>
    ) : null
}

function NavigationItem({
    item,
    expanded,
    shortEventName,
}: {
    item: PerformanceEvent
    expanded: boolean
    shortEventName: string
}): JSX.Element | null {
    return (
        <>
            <div className="flex gap-2 items-start p-2 text-xs">
                <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                    Navigated to {shortEventName}
                </span>
            </div>
            <LemonDivider className="my-0" />
            <div className="flex items-center p-2">
                {performanceSummaryCards.map(({ label, description, key, scoreBenchmarks }, index) => (
                    <Fragment key={key}>
                        {index !== 0 && <LemonDivider vertical dashed />}
                        <Tooltip title={description}>
                            <div className="flex-1 p-2 text-center">
                                <div className="text-sm">{label}</div>
                                <div className="text-lg font-semibold">
                                    {item?.[key] === undefined ? (
                                        '-'
                                    ) : (
                                        <span
                                            className={clsx({
                                                'text-danger-dark': item[key] >= scoreBenchmarks[1],
                                                'text-warning-dark':
                                                    item[key] >= scoreBenchmarks[0] && item[key] < scoreBenchmarks[1],
                                            })}
                                        >
                                            {humanFriendlyMilliseconds(item[key])}
                                        </span>
                                    )}
                                </div>
                            </div>
                        </Tooltip>
                    </Fragment>
                ))}
            </div>
        </>
    )
}
