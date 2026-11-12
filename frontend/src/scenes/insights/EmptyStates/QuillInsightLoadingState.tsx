import type { ReactNode } from 'react'
import { TextMorph } from 'torph/react'

import { Text, cn } from '@posthog/quill'

import { QuillInsightVisualizationSkeleton } from 'lib/components/Cards/InsightCard/QuillInsightVisualizationSkeleton'

import type { InsightModel } from '~/types'

export function QuillInsightLoadingState({
    query,
    message,
    suggestion,
    details,
    reserveChartHeight,
}: {
    query?: InsightModel['query']
    message: string
    suggestion: ReactNode
    details: ReactNode
    reserveChartHeight: boolean
}): JSX.Element {
    return (
        // pinned: stories and autocapture select on this data-attr value, so do not rename it
        <div
            data-quill
            data-attr="insight-empty-state"
            aria-busy="true"
            className={cn(
                'flex w-full flex-col gap-3 p-4',
                // The chart has this height and margin once it loads, so the page does not jump.
                reserveChartHeight ? 'my-2 h-(--insight-viz-min-height) min-h-fit flex-none' : 'min-h-0 flex-1'
            )}
        >
            <QuillInsightVisualizationSkeleton query={query} className="min-h-20" />
            <div className="mx-auto flex w-full max-w-120 flex-col items-center gap-1 text-center">
                <Text size="sm" weight="medium" className="m-0">
                    <TextMorph as="span">{message}</TextMorph>
                </Text>
                {suggestion}
                {details}
            </div>
        </div>
    )
}
