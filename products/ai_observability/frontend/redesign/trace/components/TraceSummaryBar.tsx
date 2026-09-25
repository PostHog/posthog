import { LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { NodeStats, PersonLink } from '../types'
import { NodeStatsLine } from './NodeStatsLine'
import { PersonChip } from './PersonChip'
import { TraceIdChip } from './TraceIdChip'

export interface TraceSummaryBarProps {
    traceId: string
    timestamp: string
    person: PersonLink | null
    totals: NodeStats
}

export function TraceSummaryBar({ traceId, timestamp, person, totals }: TraceSummaryBarProps): JSX.Element {
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
                            formatTime="h:mm A"
                        />
                    </LemonTag>
                    {person ? <PersonChip person={person} /> : null}
                </div>
                <NodeStatsLine stats={totals} className="@2xl:ml-auto" />
            </div>
        </div>
    )
}
