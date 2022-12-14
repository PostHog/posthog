import clsx from 'clsx'
import { humanizeBytes } from 'lib/utils'
import { useState } from 'react'
import { PerformanceEvent } from '~/types'

export interface ItemPerformanceEvent {
    item: PerformanceEvent
}

export function ItemPerformanceEvent({ item }: ItemPerformanceEvent): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const duration = item.duration || 0
    const bytes = humanizeBytes(item.encoded_body_size || item.decoded_body_size || 0)
    const hightlightColor = duration > 2000 ? 'danger' : duration > 500 ? 'warning' : ''

    return (
        <div
            className={clsx(
                'flex-1 border-b border-b-border-light cursor-pointer',
                hightlightColor && `bg-${hightlightColor}-highlight`,
                hightlightColor && `text-${hightlightColor}-dark`,
                expanded && 'bg-light'
            )}
            onClick={() => setExpanded(!expanded)}
        >
            <div className="flex gap-2 items-center h-10 p-2 whitespace-nowrap">
                {['resource', 'navigation'].includes(item.entry_type || '') && (
                    <>
                        <span className="text-xs truncate flex-1">{item.name}</span>
                        <span className="text-xs font-semibold">{bytes}</span>
                        <span className="text-xs font-semibold">{duration}ms</span>
                    </>
                )}
            </div>

            {expanded && (
                <div className="p-2 text-sm">
                    <>
                        <p>
                            started at {item.start_time || item.fetch_start}ms and took {item.duration}ms to complete
                        </p>

                        {item.decoded_body_size && item.encoded_body_size && (
                            <>
                                <hr />
                                Resource is {humanizeBytes(item.decoded_body_size)}
                                {item.encoded_body_size !== item.decoded_body_size && (
                                    <p>
                                        Was compressed. Sent {humanizeBytes(item.encoded_body_size)}. Saving{' '}
                                        {(
                                            ((item.decoded_body_size - item.encoded_body_size) /
                                                item.decoded_body_size) *
                                            100
                                        ).toFixed(1)}
                                        %
                                    </p>
                                )}
                            </>
                        )}
                    </>
                </div>
            )}
        </div>
    )
}
