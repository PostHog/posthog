import { Skeleton } from '@posthog/quill'

import { ChartFrameSkeleton } from '../../ChartFrameSkeleton'

// Fixed heights, so every load draws the same outline and a story renders the same picture on each run.
const BAR_HEIGHTS = ['h-1/3', 'h-1/2', 'h-2/5', 'h-3/5', 'h-1/2', 'h-3/4', 'h-3/5', 'h-4/5', 'h-2/3', 'h-5/6']

export function BarLoading(): JSX.Element {
    return (
        <ChartFrameSkeleton>
            {BAR_HEIGHTS.map((heightClass, index) => (
                <Skeleton key={index} className={`flex-1 rounded-b-none ${heightClass}`} />
            ))}
        </ChartFrameSkeleton>
    )
}
