import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { LabeledLink } from '../types'
import { EvalsChip, EvalsChipProps } from './EvalsChip'
import { FeedbackChip, FeedbackChipProps } from './FeedbackChip'
import { GitBranchChip, GitBranchChipProps } from './GitBranchChip'
import { NodeStatsLine } from './NodeStatsLine'
import { PersonChip } from './PersonChip'
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
}: TraceSummaryBarProps): JSX.Element {
    return (
        <div className="@container">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <TraceIdChip traceId={traceId} />
                    <LemonTag weight="normal">
                        <TZLabel
                            time={timestamp}
                            timestampStyle="absolute"
                            formatDate="MMM D, YYYY"
                            formatTime="HH:mm"
                        />
                    </LemonTag>
                    {person ? <PersonChip person={person} /> : null}
                    {clusters ? <TraceClustersChip {...clusters} /> : null}
                    {evals ? <EvalsChip {...evals} /> : null}
                    {feedback ? <FeedbackChip {...feedback} /> : null}
                    {git ? <GitBranchChip {...git} /> : null}
                </div>
                <NodeStatsLine stats={totals} className="@2xl:ml-auto" />
            </div>
        </div>
    )
}
