import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, humanizeBytes, humanFriendlyMilliseconds, isURL } from 'lib/utils'
import { PerformanceEvent } from '~/types'
import { SimpleKeyValueList } from './SimpleKeyValueList'
import { InfoCircleOutlined } from '@ant-design/icons'
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
                <Link disableClientSideRouting to="https://web.dev/fcp/" target="_blank">
                    Read more on web.dev
                </Link>
            </div>
        ),
        key: 'first_contentful_paint',
        scoreBenchmarks: [1800, 3000],
    },
    {
        label: 'Time to Interactive',
        description: (
            <div>
                The Time to Interactive (TTI) metric measures the time from when the page starts loading to when its
                main sub-resources have loaded and it is capable of reliably responding to user input quickly.{' '}
                <Link disableClientSideRouting to="https://web.dev/tti/" target="_blank">
                    Read more on web.dev
                </Link>
            </div>
        ),
        key: 'time_to_interactive',
        scoreBenchmarks: [3800, 7300],
    },
    {
        label: 'Total Blocking Time',
        description: (
            <div>
                The Total Blocking Time (TBT) metric measures the total amount of time between First Contentful Paint
                (FCP) and Time to Interactive (TTI) where the main thread was blocked for long enough to prevent input
                responsiveness.{' '}
                <Link disableClientSideRouting to="https://web.dev/tbt/" target="_blank">
                    Read more on web.dev
                </Link>
            </div>
        ),
        key: 'total_blocking_time',
        scoreBenchmarks: [200, 600],
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

    console.log('SANITIZED', sanitizedProps)

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
                    {item.entry_type === 'performance-summary' ? (
                        <>
                            <div className="flex items-center p-2">
                                {performanceSummaryCards.map(({ label, description, key, scoreBenchmarks }, index) => (
                                    <Fragment key={key}>
                                        {index !== 0 && <LemonDivider vertical dashed />}
                                        <div className="flex-1 p-2 text-center">
                                            <div className="text-sm font-semibold">
                                                {label}
                                                <Tooltip isDefaultTooltip title={description}>
                                                    <InfoCircleOutlined className="ml-2 text-xs" />
                                                </Tooltip>
                                            </div>
                                            <div className="text-lg">
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
                                    </Fragment>
                                ))}
                            </div>
                        </>
                    ) : item.entry_type === 'navigation' ? (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                                Navigated to {eventName}
                            </span>
                            {renderTimeBenchmark(duration)}
                        </div>
                    ) : item.entry_type === 'paint' ? (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                                {capitalizeFirstLetter(eventName?.replace(/-/g, ' ') || '')}
                            </span>{' '}
                            {renderTimeBenchmark(startTime)}
                        </div>
                    ) : (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>{eventName}</span>
                            <span className={clsx('font-semibold')}>{bytes}</span>
                            {renderTimeBenchmark(duration)}
                        </div>
                    )}
                </div>
            </LemonButton>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    {item.entry_type === 'paint' ? (
                        <p>
                            {item.name === 'first-paint' ? (
                                <>
                                    <b>First Paint</b> is the time between navigation and when the browser first renders
                                    pixels to the screen, rendering anything that is visually different from the default
                                    background color of the body. It is the first key moment in page load and will
                                    answer the question "Has the browser started to render the page?"
                                    <br />
                                    <Link
                                        to="https://developer.mozilla.org/en-US/docs/Glossary/First_paint"
                                        target="_blank"
                                    >
                                        Read more on the mozilla developer network
                                    </Link>
                                </>
                            ) : item.name === 'first-contentful-paint' ? (
                                <>
                                    <b>First Contentful Paint (FCP)</b> is when the browser renders the first bit of
                                    content from the DOM, providing the first feedback to the user that the page is
                                    actually loading. <br />
                                    <Link
                                        to="https://developer.mozilla.org/en-US/docs/Glossary/First_contentful_paint"
                                        target="_blank"
                                    >
                                        Read more on the mozilla developer network
                                    </Link>
                                </>
                            ) : null}
                        </p>
                    ) : (
                        <>
                            <CodeSnippet language={Language.Markup} wrap copyDescription="performance event name">
                                {item.name}
                            </CodeSnippet>
                            <p>
                                started at <b>{humanFriendlyMilliseconds(item.start_time || item.fetch_start)}</b> and
                                took <b>{humanFriendlyMilliseconds(item.duration)}</b> to complete
                            </p>
                        </>
                    )}

                    {item.decoded_body_size && item.encoded_body_size ? (
                        <span>
                            Resource is {humanizeBytes(item.decoded_body_size)}.
                            {item.encoded_body_size !== item.decoded_body_size && (
                                <>
                                    {' '}
                                    Was compressed. Sent {humanizeBytes(item.encoded_body_size)}. Saving{' '}
                                    {(
                                        ((item.decoded_body_size - item.encoded_body_size) / item.decoded_body_size) *
                                        100
                                    ).toFixed(1)}
                                    %
                                </>
                            )}
                        </span>
                    ) : null}
                    <LemonDivider dashed />
                    <SimpleKeyValueList item={sanitizedProps} />
                </div>
            )}
        </div>
    )
}
