import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter, humanizeBytes, humanFriendlyMilliseconds } from 'lib/utils'
import { PerformanceEvent } from '~/types'
import { SimpleKeyValueList } from './SimpleKeyValueList'

export interface ItemPerformanceEvent {
    item: PerformanceEvent
    expanded: boolean
    setExpanded: (expanded: boolean) => void
    finalTimestamp?: Dayjs
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
    const contextLengthMs = finalTimestamp?.diff(dayjs(item.time_origin), 'ms') || 1000

    const {
        timestamp,
        uuid,
        session_id,
        window_id,
        pageview_id,
        distinct_id,
        time_origin,
        entry_type,
        name,
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
                            <div className="flex items-center p-2">
                                <div className="flex-1 p-2 text-center">
                                    <div className="text-sm font-semibold">Interactive</div>
                                    <div className="text-lg">{humanFriendlyMilliseconds(item.dom_interactive)}</div>
                                </div>
                                <LemonDivider vertical dashed />
                                <div className="flex-1 p-2 text-center">
                                    <div className="text-sm font-semibold">Ready</div>
                                    <div className="text-lg">{humanFriendlyMilliseconds(item.dom_complete)}</div>
                                </div>
                                <LemonDivider vertical dashed />
                                <div className="flex-1 p-2 text-center">
                                    <div className="text-sm font-semibold">Done</div>
                                    <div className="text-lg">{humanFriendlyMilliseconds(item.duration)}</div>
                                </div>
                            </div>
                            <div className={clsx('text-xs flex-1 overflow-hidden p-2', !expanded && 'truncate')}>
                                {item.name}
                            </div>
                        </>
                    ) : item.entry_type === 'paint' ? (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>
                                {capitalizeFirstLetter(item.name?.replace(/-/g, ' ') || '')}
                            </span>
                            <span
                                className={clsx('font-semibold', {
                                    'text-danger-dark': startTime >= 2000,
                                    'text-warning-dark': startTime > 500 && startTime < 2000,
                                })}
                            >
                                {humanFriendlyMilliseconds(startTime)}
                            </span>
                        </div>
                    ) : (
                        <div className="flex gap-2 items-start p-2 text-xs cursor-pointer">
                            <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>{item.name}</span>
                            <span className={clsx('font-semibold')}>{bytes}</span>
                            <span
                                className={clsx('font-semibold', {
                                    'text-danger-dark': duration >= 2000,
                                    'text-warning-dark': duration > 500 && duration < 2000,
                                })}
                            >
                                {humanFriendlyMilliseconds(duration)}
                            </span>
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
                        <p>
                            started at <b>{humanFriendlyMilliseconds(item.start_time || item.fetch_start)}</b> and took{' '}
                            <b>{humanFriendlyMilliseconds(item.duration)}</b> to complete
                        </p>
                    )}

                    {item.decoded_body_size && item.encoded_body_size ? (
                        <>
                            Resource is {humanizeBytes(item.decoded_body_size)}
                            {item.encoded_body_size !== item.decoded_body_size && (
                                <p>
                                    Was compressed. Sent {humanizeBytes(item.encoded_body_size)}. Saving{' '}
                                    {(
                                        ((item.decoded_body_size - item.encoded_body_size) / item.decoded_body_size) *
                                        100
                                    ).toFixed(1)}
                                    %
                                </p>
                            )}
                        </>
                    ) : null}
                    <LemonDivider dashed />
                    <SimpleKeyValueList item={sanitizedProps} />
                </div>
            )}
        </div>
    )
}
