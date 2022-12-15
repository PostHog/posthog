import { LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { dayjs, Dayjs } from 'lib/dayjs'
import { humanizeBytes } from 'lib/utils'
import { useState } from 'react'
import { PerformanceEvent } from '~/types'
import { SimpleKeyValueList } from './SimpleKeyValueList'

export interface ItemPerformanceEvent {
    item: PerformanceEvent
    finalTimestamp?: Dayjs
}

const ms = (timestamp: number | undefined): string | undefined => {
    if (typeof timestamp !== 'number') {
        return undefined
    }

    if (timestamp < 1000) {
        return `${Math.ceil(timestamp)}ms`
    }

    return `${(timestamp / 1000).toFixed(2)}s`
}

export function ItemPerformanceEvent({ item, finalTimestamp }: ItemPerformanceEvent): JSX.Element {
    const [expanded, setExpanded] = useState(false)
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

    return (
        <div className={clsx('rounded bg-light border', expanded && 'border-primary')}>
            <div className="relative cursor-pointer" onClick={() => setExpanded(!expanded)}>
                <div
                    className="absolute bottom-0 bg-primary"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        height: 2,
                        left: `${(startTime / contextLengthMs) * 100}%`,
                        width: `${Math.max((duration / contextLengthMs) * 100, 0.5)}%`,
                    }}
                />
                {item.entry_type === 'navigation' ? (
                    <>
                        <div className="flex items-center p-2">
                            <div className="flex-1 p-2 text-center">
                                <div className="text-sm font-semibold">Interactive</div>
                                <div className="text-lg">{ms(item.dom_interactive)}</div>
                            </div>
                            <LemonDivider vertical dashed />
                            <div className="flex-1 p-2 text-center">
                                <div className="text-sm font-semibold">Ready</div>
                                <div className="text-lg">{ms(item.dom_complete)}</div>
                            </div>
                            <LemonDivider vertical dashed />
                            <div className="flex-1 p-2 text-center">
                                <div className="text-sm font-semibold">Done</div>
                                <div className="text-lg">{ms(item.duration)}</div>
                            </div>
                        </div>
                        <div className={clsx('text-xs flex-1 overflow-hidden p-2', !expanded && 'truncate')}>
                            {item.name}
                        </div>
                    </>
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
                            {ms(duration)}
                        </span>
                    </div>
                )}
            </div>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <p>
                        started at <b>{ms(item.start_time || item.fetch_start)}</b> and took <b>{ms(item.duration)}</b>{' '}
                        to complete
                    </p>
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
                    <SimpleKeyValueList item={otherProps} />
                </div>
            )}
        </div>
    )
}
