import { useCallback, useMemo, useState } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

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
    // line-clamp-3 constrains clientHeight to the visible area;
    // if scrollHeight exceeds it, the content is truncated and we show a toggle
    const valueRef = useCallback((node: HTMLDivElement | null) => {
        if (node) {
            setIsClamped(node.scrollHeight > node.clientHeight)
        }
    }, [])

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
                        <button
                            type="button"
                            onClick={() => setExpanded(!expanded)}
                            className="text-xs text-muted hover:text-default mt-0.5 cursor-pointer"
                        >
                            {expanded ? 'Show less' : 'Show more…'}
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}
