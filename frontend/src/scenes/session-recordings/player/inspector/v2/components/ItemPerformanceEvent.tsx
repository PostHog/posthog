import { LemonButton } from '@posthog/lemon-ui'
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

    return (
        <div className={clsx('rounded bg-light border')}>
            <div className="flex gap-2 items-start p-2 text-xs cursor-pointer" onClick={() => setExpanded(!expanded)}>
                {['resource', 'navigation'].includes(item.entry_type || '') && (
                    <>
                        <span className={clsx('flex-1 overflow-hidden', !expanded && 'truncate')}>{item.name}</span>
                        <span className={clsx('font-semibold')}>{bytes}</span>
                        <span
                            className={clsx('font-semibold', {
                                'text-danger-dark': duration >= 2000,
                                'text-warning-dark': duration > 500 && duration < 2000,
                            })}
                        >
                            {duration}ms
                        </span>
                    </>
                )}
            </div>

            {expanded && (
                <div className="p-2 text-xs border-t">
                    <div className="flex justify-end">
                        <LemonButton type="secondary" size="small">
                            Copy
                        </LemonButton>
                    </div>
                    <>
                        <p>
                            started at <b>{item.start_time || item.fetch_start}ms</b> and took <b>{item.duration}ms</b>{' '}
                            to complete
                        </p>

                        {item.decoded_body_size && item.encoded_body_size ? (
                            <>
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
                        ) : null}

                        <pre>
                            <code>{JSON.stringify(item, null, 2)}</code>
                        </pre>
                    </>
                </div>
            )}
        </div>
    )
}
