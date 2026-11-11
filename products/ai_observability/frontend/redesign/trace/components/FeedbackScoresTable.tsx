import { LemonTable } from '@posthog/lemon-ui'

import type { TraceFeedbackScoreApi } from '../../../generated/api.schemas'
import { FeedbackStepContext } from '../types'
import { FeedbackStepLink } from './FeedbackStepLink'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ShortTimestamp } from './ShortTimestamp'

export interface FeedbackScoresTableProps {
    scores: TraceFeedbackScoreApi[]
    steps: FeedbackStepContext
    onSelectStep: (nodeId: string) => void
    /** The row to bring into view, the first one of the step the mode was opened from. */
    scrollTargetId: string | null
}

export function FeedbackScoresTable({
    scores,
    steps,
    onSelectStep,
    scrollTargetId,
}: FeedbackScoresTableProps): JSX.Element {
    return (
        <LemonTable<TraceFeedbackScoreApi>
            dataSource={scores}
            rowKey="id"
            size="small"
            rowStatus={(row) => (row.nodeId === steps.focusNodeId ? 'highlighted' : null)}
            onRow={(row) => (row.id === scrollTargetId ? { ref: scrollIntoNearest } : {})}
            columns={[
                {
                    title: 'Score',
                    key: 'name',
                    render: (_, row) => (
                        <span className={row.name ? 'font-semibold' : 'text-secondary'}>
                            {row.name ?? 'Unnamed score'}
                        </span>
                    ),
                },
                {
                    title: 'Value',
                    key: 'value',
                    render: (_, row) => <span className="break-all font-mono">{row.value}</span>,
                },
                {
                    title: 'Step',
                    key: 'step',
                    render: (_, row) => (
                        <FeedbackStepLink nodeId={row.nodeId} steps={steps} onSelectStep={onSelectStep} />
                    ),
                },
                {
                    title: 'Time',
                    key: 'timestamp',
                    render: (_, row) => <ShortTimestamp time={row.timestamp} />,
                },
            ]}
        />
    )
}
