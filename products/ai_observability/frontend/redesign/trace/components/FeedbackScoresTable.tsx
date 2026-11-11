import { LemonTable } from '@posthog/lemon-ui'

import { FeedbackScoreRow } from '../types'
import { FeedbackStepLink } from './FeedbackStepLink'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ShortTimestamp } from './ShortTimestamp'

export interface FeedbackScoresTableProps {
    scores: FeedbackScoreRow[]
    onSelectStep: (nodeId: string) => void
    /** The row to bring into view, the first one of the step the mode was opened from. */
    scrollTargetId: string | null
}

export function FeedbackScoresTable({ scores, onSelectStep, scrollTargetId }: FeedbackScoresTableProps): JSX.Element {
    return (
        <LemonTable<FeedbackScoreRow>
            dataSource={scores}
            rowKey="id"
            size="small"
            rowStatus={(row) => (row.focused ? 'highlighted' : null)}
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
                    render: (_, row) => <FeedbackStepLink step={row.step} onSelectStep={onSelectStep} />,
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
