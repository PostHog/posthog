import { type ComponentType, Suspense } from 'react'

import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SAMPLE_FRAMES } from './data/sampleFrames'
import type { VizDefinition } from './vizTypes'

/**
 * A kind of chart drawn from made-up frames and marked as sample data. It is faded and ignores the pointer, because its
 * numbers are invented and nothing may read them back out.
 */
export function ChartSampleData<Options>({
    viz,
    options,
    Loading,
}: {
    viz: VizDefinition<Options>
    options: Options
    Loading: ComponentType<{ options: Options }>
}): JSX.Element {
    return (
        <div className="relative flex min-h-0 flex-1 flex-col" data-attr="dashboard-v2-sample-data">
            <Tooltip>
                <TooltipTrigger render={<Badge className="absolute top-0 right-0 z-1 cursor-help" tabIndex={0} />}>
                    Sample data
                </TooltipTrigger>
                <TooltipContent className="max-w-72">
                    This chart shows made-up data. Your real data shows here once it starts coming in.
                </TooltipContent>
            </Tooltip>
            <div
                className="pointer-events-none relative flex min-h-0 w-full flex-1 flex-col opacity-50"
                aria-hidden="true"
            >
                <Suspense fallback={<Loading options={options} />}>
                    <viz.Component frames={SAMPLE_FRAMES} options={options} />
                </Suspense>
            </div>
        </div>
    )
}
