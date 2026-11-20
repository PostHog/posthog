import { LemonSkeleton } from '@posthog/lemon-ui'

import { TraceBodyLoading } from './TraceBodyLoading'

export function TraceViewLoading(): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <LemonSkeleton className="h-7 w-1/3" />
            <LemonSkeleton className="h-5 w-1/2" />
            <TraceBodyLoading />
        </div>
    )
}
