import { useMemo } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { RuntimeIcon } from 'products/error_tracking/frontend/components/RuntimeIcon'

import { FingerprintRecordPartDisplay } from '../FingerprintRecordPartDisplay'
import { ErrorTrackingException, ErrorTrackingRuntime, FingerprintRecordPart } from '../types'
import { formatType } from '../utils'

export type ExceptionHeaderProps = {
    exception: ErrorTrackingException
    runtime?: ErrorTrackingRuntime
    loading?: boolean
    part?: FingerprintRecordPart
    fingerprint?: FingerprintRecordPart
    truncate?: boolean
}

// export function ExceptionHeader({ exception, part, fingerprint }: ExceptionHeaderProps): JSX.Element {
//     const type = formatType(exception)
//     const value = exception.value

//     return (
//         <div className="flex flex-col gap-0.5 mb-2">
//             <h3 className="StackTrace__type mb-0 flex items-center" title={type}>
//                 {type}
//                 {part && <FingerprintRecordPartDisplay className="ml-1" part={part} />}
//             </h3>
//             {value && (
//                 <div className="StackTrace__value line-clamp-2 text-secondary italic text-xs" title={value}>
//                     {value}
//                 </div>
//             )}
//         </div>
//     )
// }

export function ExceptionHeader({
    exception,
    runtime,
    part,
    loading,
    truncate = true,
}: ExceptionHeaderProps): JSX.Element {
    const type = useMemo(() => formatType(exception), [exception])
    const { value } = exception

    return (
        <div className="pb-1">
            <div className="flex gap-2 items-center">
                {loading ? (
                    <LemonSkeleton className="w-[25%] h-2" />
                ) : (
                    <>
                        {runtime && <RuntimeIcon runtime={runtime} className="ml-1" />}
                        <span className="font-semibold text-lg mb-0">{type}</span>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </>
                )}
            </div>
            {(loading || value) && (
                <div
                    className={cn('text-[var(--gray-8)] leading-6', {
                        'line-clamp-1': truncate,
                    })}
                >
                    {loading ? <LemonSkeleton className="w-[50%] h-2" /> : value}
                </div>
            )}
        </div>
    )
}
