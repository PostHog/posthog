import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { humanizeBytes, humanFriendlyMilliseconds, isURL } from 'lib/utils'
import { PerformanceEvent } from '~/types'
import { SimpleKeyValueList } from './SimpleKeyValueList'
import { Tooltip } from 'lib/components/Tooltip'
import { Fragment } from 'react'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

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

export function ItemPerformanceEvent({
    item,
    finalTimestamp,
    expanded,
    setExpanded,
}: ItemPerformanceEvent): JSX.Element {
    const bytes = humanizeBytes(item.encoded_body_size || item.decoded_body_size || 0)
    const startTime = item.start_time || item.fetch_start || 0
    const duration = item.duration || 0
    const eventName = item.name && isURL(item.name) ? new URL(item.name).pathname : item.name || '(empty string)'
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

        return {
            ...acc,
            [key]: typeof value === 'number' ? Math.round(value) : value,
        }
    }, {} as Record<string, any>)

    const compressionPercentage =
        item.decoded_body_size && item.encoded_body_size
            ? ((item.decoded_body_size - item.encoded_body_size) / item.decoded_body_size) * 100
            : undefined

    return (
        <div>
            <LemonButton noPadding onClick={() => setExpanded(!expanded)} status={'primary-alt'} fullWidth>
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
                        <>
                            <div className="flex gap-2 items-start p-2 text-xs">
                                <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                                    Navigated to {eventName}
                                </span>
                            </div>
                            <LemonDivider className="my-0" />
                            <div className="flex items-center p-2">
                                {performanceSummaryCards.map(({ label, description, key, scoreBenchmarks }, index) => (
                                    <Fragment key={key}>
                                        {index !== 0 && <LemonDivider vertical dashed />}
                                        <Tooltip isDefaultTooltip title={description}>
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
                                                                    item[key] >= scoreBenchmarks[0] &&
                                                                    item[key] < scoreBenchmarks[1],
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
                    ) : (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>{eventName}</span>
                            {/* We only show the status if it exists and is an error status */}
                            {otherProps.response_status && otherProps.response_status >= 400 ? (
                                <span
                                    className={clsx('font-semibold', {
                                        'text-danger-dark': otherProps.response_status >= 400,
                                    })}
                                >
                                    {otherProps.response_status}
                                </span>
                            ) : null}
                            {renderTimeBenchmark(duration)}
                            <span className={clsx('font-semibold')}>{bytes}</span>
                        </div>
                    )}
                </div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <CodeSnippet language={Language.Markup} wrap copyDescription="performance event name">
                        {item.name}
                    </CodeSnippet>

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
                        <p>
                            Request started at <b>{humanFriendlyMilliseconds(item.start_time || item.fetch_start)}</b>{' '}
                            and took <b>{humanFriendlyMilliseconds(item.duration)}</b>
                            {item.decoded_body_size ? (
                                <>
                                    {' '}
                                    to load <b>{humanizeBytes(item.decoded_body_size)}</b> of data
                                </>
                            ) : null}
                            {compressionPercentage && item.encoded_body_size ? (
                                <>
                                    , compressed to <b>{humanizeBytes(item.encoded_body_size)}</b> saving{' '}
                                    <b>{compressionPercentage.toFixed(1)}%</b>
                                </>
                            ) : null}
                            .
                        </p>
                    )}

                    <LemonDivider dashed />
                    <SimpleKeyValueList item={sanitizedProps} />
                </div>
            )}
        </div>
    )
}
