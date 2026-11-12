import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { TraceApi, TraceClusterApi } from '../../../generated/api.schemas'
import { EvalsChip, EvalsChipProps } from './EvalsChip'
import { FeedbackChip, FeedbackChipProps } from './FeedbackChip'
import { GitBranchChip, GitBranchChipProps } from './GitBranchChip'
import { LabeledChipValue } from './LabeledChipValue'
import { NodeStatsLine } from './NodeStatsLine'
import { PersonChip } from './PersonChip'
import { ReviewChip, ReviewChipProps } from './ReviewChip'
import { TraceClustersChip } from './TraceClustersChip'
import { TraceIdChip } from './TraceIdChip'

export interface TraceSummaryBarProps {
    trace: Pick<TraceApi, 'id' | 'createdAt' | 'person' | 'totals'>
    clusters?: TraceClusterApi[] | null
    evals?: EvalsChipProps | null
    feedback?: FeedbackChipProps | null
    git?: GitBranchChipProps | null
    review?: ReviewChipProps | null
}

export function TraceSummaryBar({
    trace,
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
                <TraceIdChip traceId={trace.id} />
                <LemonTag weight="normal">
                    <LabeledChipValue label="Time" icon={<IconClock />}>
                        <TZLabel
                            time={trace.createdAt}
                            timestampStyle="absolute"
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                            // The default dotted border adds a pixel, which makes this chip taller than its neighbours.
                            className="border-b-0 underline decoration-dotted underline-offset-2"
                        />
                    </LabeledChipValue>
                </LemonTag>
                {trace.person ? (
                    <PersonChip
                        person={{
                            label: trace.person.label,
                            href: urls.personByDistinctId(trace.person.distinctId),
                        }}
                    />
                ) : null}
                {clusters ? <TraceClustersChip clusters={clusters} /> : null}
                {evals ? <EvalsChip {...evals} /> : null}
                {feedback ? <FeedbackChip {...feedback} /> : null}
                {review ? <ReviewChip {...review} /> : null}
                {git ? <GitBranchChip {...git} /> : null}
            </div>
            <span aria-hidden className="grow" />
            <NodeStatsLine stats={trace.totals} wrap className="leading-[1.375rem]" />
        </div>
    )
}
