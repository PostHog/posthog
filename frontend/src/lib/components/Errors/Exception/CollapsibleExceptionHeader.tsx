import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonButton, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { ErrorTrackingException, ErrorTrackingRuntime, FingerprintRecordPart } from '../types'
import { formatType } from '../utils'

export type CollapsibleExceptionHeaderProps = {
    exception: ErrorTrackingException
    runtime?: ErrorTrackingRuntime
    loading?: boolean
    part?: FingerprintRecordPart
    fingerprint?: FingerprintRecordPart
    truncate?: boolean
}

export function CollapsibleExceptionHeader({
    exception,
    runtime,
    part,
    loading,
    truncate = false,
}: CollapsibleExceptionHeaderProps): JSX.Element {
    const type = useMemo(() => formatType(exception), [exception])
    const { value } = exception

    const [expanded, setExpanded] = useState(false)
    const [isClamped, setIsClamped] = useState(false)
    const valueRef = useRef<HTMLDivElement | null>(null)

    // line-clamp-3 constrains clientHeight to the visible area;
    // if scrollHeight exceeds it, the content is truncated and we show a toggle.
    // Only re-check when value changes (not on expand, since unclamped scrollHeight === clientHeight).
    useEffect(() => {
        if (valueRef.current) {
            setIsClamped(valueRef.current.scrollHeight > valueRef.current.clientHeight)
        }
    }, [value])

    // Reset collapsed state when viewing a different exception
    useEffect(() => {
        setExpanded(false)
    }, [value])

    return (
        <div className="pb-1">
            <div className="flex gap-2 items-center min-w-0">
                {loading ? (
                    <LemonSkeleton className="w-[25%] h-2" />
                ) : (
                    <>
                        {runtime && <RuntimeIcon runtime={runtime} className="ml-1 shrink-0" />}
                        <Tooltip title={type} delayMs={300}>
                            <span className="font-semibold text-lg mb-0 truncate">{type}</span>
                        </Tooltip>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </>
                )}
            </div>
            {(loading || value) && (
                <div>
                    <div
                        ref={valueRef}
                        className={cn('text-[var(--gray-8)] leading-6 whitespace-pre-wrap', {
                            'line-clamp-1': truncate,
                            'line-clamp-3': !truncate && !expanded,
                        })}
                    >
                        {loading ? <LemonSkeleton className="w-[50%] h-2" /> : value}
                    </div>
                    {!truncate && isClamped && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            onClick={() => setExpanded(!expanded)}
                            className="mt-0.5 underline"
                        >
                            {expanded ? 'Show less' : 'Show more'}
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
