import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { LabeledLink } from '../types'
import { EvalsChip, EvalsChipProps } from './EvalsChip'
import { FeedbackChip, FeedbackChipProps } from './FeedbackChip'
import { GitBranchChip, GitBranchChipProps } from './GitBranchChip'
import { LabeledChipValue } from './LabeledChipValue'
import { NodeStatsLine } from './NodeStatsLine'
import { PersonChip } from './PersonChip'
import { ReviewChip, ReviewChipProps } from './ReviewChip'
import { TraceClustersChip, TraceClustersChipProps } from './TraceClustersChip'
import { TraceIdChip } from './TraceIdChip'

export interface TraceSummaryBarProps {
    traceId: string
    timestamp: string
    person: LabeledLink | null
    totals: TraceNodeStatsApi
    clusters?: TraceClustersChipProps | null
    evals?: EvalsChipProps | null
    feedback?: FeedbackChipProps | null
    git?: GitBranchChipProps | null
    review?: ReviewChipProps | null
}

export function TraceSummaryBar({
    traceId,
    timestamp,
    person,
    totals,
    clusters = null,
    evals = null,
    feedback = null,
    git = null,
    review = null,
}: TraceSummaryBarProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-y-2.5">
            {/* The chips cap at a full line and the empty spacer stays on their line, so stats that fit beside the chips
                are pushed right, and stats that wrap start their own line on the left. */}
            <div className="flex max-w-full min-w-0 flex-wrap items-center gap-1.5 pr-3">
                <TraceIdChip traceId={traceId} />
                <LemonTag weight="normal">
                    <LabeledChipValue label="Time" icon={<IconClock />}>
                        <TZLabel
                            time={timestamp}
                            timestampStyle="absolute"
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                            // The default dotted border adds a pixel, which makes this chip taller than its neighbours.
                            className="border-b-0 underline decoration-dotted underline-offset-2"
                        />
                    </LabeledChipValue>
                </LemonTag>
                {person ? <PersonChip person={person} /> : null}
                {clusters ? <TraceClustersChip {...clusters} /> : null}
                {evals ? <EvalsChip {...evals} /> : null}
                {feedback ? <FeedbackChip {...feedback} /> : null}
                {review ? <ReviewChip {...review} /> : null}
                {git ? <GitBranchChip {...git} /> : null}
            </div>
            <span aria-hidden className="grow" />
            <NodeStatsLine stats={totals} wrap className="leading-[1.375rem]" />
        </div>
    )
}
