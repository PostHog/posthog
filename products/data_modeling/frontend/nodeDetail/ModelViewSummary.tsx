import type { ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ModelDownstreamSummary } from './ModelDownstreamSummary'
import { ModelSummaryCard } from './ModelSummaryCard'

export function ModelViewSummary({
    downstreamCount,
    lineageUrl,
    metadata,
}: {
    downstreamCount: number
    lineageUrl: string
    metadata?: ReactNode
}): JSX.Element {
    return (
        <ModelSummaryCard metadata={metadata} dataAttr="node-detail-view-summary">
            <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">Runs on demand</span>
                    <Tooltip title="Materialize to store results and refresh them on a schedule.">
                        <span
                            tabIndex={0}
                            aria-label="About on-demand views"
                            className="flex text-secondary cursor-help"
                        >
                            <IconInfo />
                        </span>
                    </Tooltip>
                </div>
                <dl className="flex flex-wrap gap-x-10 gap-y-3 mb-0 text-sm">
                    <ModelDownstreamSummary downstreamCount={downstreamCount} lineageUrl={lineageUrl} />
                </dl>
            </div>
        </ModelSummaryCard>
    )
}
