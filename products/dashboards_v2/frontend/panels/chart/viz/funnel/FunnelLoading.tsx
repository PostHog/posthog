import { Skeleton } from '@posthog/quill'

import { ChartFrameSkeleton } from '../../ChartFrameSkeleton'

const STEP_HEIGHTS = ['h-full', 'h-3/5', 'h-2/5', 'h-1/4']

export function FunnelLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            {STEP_HEIGHTS.map((heightClass, index) => (
                <Skeleton key={index} className={`mx-2 flex-1 rounded-b-none ${heightClass}`} />
            ))}
        </ChartFrameSkeleton>
    )
}
