import { LemonSkeleton } from '@posthog/lemon-ui'
import { FingerprintRecordPartDisplay } from 'lib/components/Errors/FingerprintRecordPartDisplay'
import { ChainedStackTraces, ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { hasStacktrace } from 'lib/components/Errors/utils'
import { cn } from 'lib/utils/css-classes'
import { useCallback } from 'react'

import { cancelEvent } from '../../utils'
import { RuntimeIcon } from '../RuntimeIcon'
import { StacktraceBaseDisplayProps, StacktraceBaseExceptionHeaderProps } from './StacktraceBase'

export function StacktraceGenericDisplay({
    className,
    truncateMessage,
    loading,
    renderLoading,
    renderEmpty,
    showAllFrames,
    attributes,
}: StacktraceBaseDisplayProps): JSX.Element {
    const { runtime, exceptionList, fingerprintRecords } = attributes || {}
    const renderExceptionHeader = useCallback(
        ({ type, value, loading, part }: ExceptionHeaderProps): JSX.Element => {
            return (
                <StacktraceGenericExceptionHeader
                    type={type}
                    value={value}
                    part={part}
                    runtime={runtime}
                    loading={loading}
                    truncate={truncateMessage}
                />
            )
        },
        [runtime, truncateMessage]
    )
    const isEmpty = !hasStacktrace(exceptionList || [])
    return (
        <div className={className}>
            {loading
                ? renderLoading(renderExceptionHeader)
                : exceptionList && (
                      <ChainedStackTraces
                          showAllFrames={showAllFrames}
                          exceptionList={exceptionList}
                          renderExceptionHeader={renderExceptionHeader}
                          fingerprintRecords={fingerprintRecords}
                          onFrameContextClick={(_, e) => cancelEvent(e)}
                      />
                  )}
            {!loading && isEmpty && renderEmpty()}
        </div>
    )
}

export function StacktraceGenericExceptionHeader({
    type,
    value,
    runtime,
    part,
    loading,
    truncate,
}: StacktraceBaseExceptionHeaderProps): JSX.Element {
    return (
        <div className="pb-1">
            <div className="flex gap-2 items-center h-6">
                {loading ? (
                    <LemonSkeleton className="w-[25%] h-2" />
                ) : (
                    <>
                        {runtime && <RuntimeIcon runtime={runtime} />}
                        <div className="font-bold text-lg">{type || 'Unknown type'}</div>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </>
                )}
            </div>
            <div
                className={cn('text-tertiary leading-6', {
                    'line-clamp-1': truncate,
                })}
            >
                {loading ? <LemonSkeleton className="w-[50%] h-2" /> : value || 'Unknown message'}
            </div>
        </div>
    )
}
