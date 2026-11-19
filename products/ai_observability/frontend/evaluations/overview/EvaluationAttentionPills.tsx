import { useActions, useValues } from 'kea'

import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { ATTENTION_LABELS } from './evaluationOverviewDisplay'
import { type AttentionFilter, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const OPTIONS: { value: AttentionFilter; label: string }[] = [
    { value: null, label: 'All' },
    { value: 'any', label: 'Needs attention' },
    ...(['errored', 'silent', 'worse'] as const).map((reason) => ({ value: reason, label: ATTENTION_LABELS[reason] })),
]

export function EvaluationAttentionPills(): JSX.Element {
    const { attentionFilter, attentionCounts } = useValues(evaluationsOverviewLogic)
    const { setAttentionFilter } = useActions(evaluationsOverviewLogic)
    // A reason no evaluation has would only filter the table to nothing, so it stays hidden unless picked.
    const shown = OPTIONS.filter(
        ({ value }) => value === null || value === attentionFilter || (attentionCounts[value] ?? 0) > 0
    )

    return (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter evaluations">
            {shown.map(({ value, label }) => (
                <LemonButton
                    key={label}
                    type="secondary"
                    size="small"
                    active={value === attentionFilter}
                    onClick={() => setAttentionFilter(value)}
                    sideIcon={
                        <LemonBadge.Number
                            count={attentionCounts[value ?? 'all'] ?? 0}
                            status={value === 'any' ? 'danger' : 'muted'}
                            size="small"
                            maxDigits={3}
                            showZero
                        />
                    }
                    data-attr={`evaluation-overview-table-filter-${value ?? 'all'}`}
                >
                    {label}
                </LemonButton>
            ))}
        </div>
    )
}
