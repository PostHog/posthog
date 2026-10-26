import { useActions, useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ATTENTION_LABELS } from './evaluationOverviewDisplay'
import { type AttentionFilter, evaluationsOverviewLogic } from './evaluationsOverviewLogic'

const OPTIONS: { value: AttentionFilter; label: string }[] = [
    { value: null, label: 'All' },
    { value: 'any', label: 'Needs attention' },
    ...(['errored', 'silent', 'worse'] as const).map((reason) => ({ value: reason, label: ATTENTION_LABELS[reason] })),
]

/** The table's attention filters as pills, so each count shows without opening a menu. */
export function EvaluationAttentionPills(): JSX.Element {
    const { attentionFilter, attentionCounts } = useValues(evaluationsOverviewLogic)
    const { setAttentionFilter } = useActions(evaluationsOverviewLogic)
    // A reason no evaluation has would only filter the table to nothing, so it stays hidden unless picked.
    const shown = OPTIONS.filter(
        ({ value }) => value === null || value === attentionFilter || (attentionCounts[value] ?? 0) > 0
    )

    return (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter evaluations">
            {shown.map(({ value, label }) => {
                const active = value === attentionFilter
                const count = attentionCounts[value ?? 'all'] ?? 0
                return (
                    <button
                        key={label}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setAttentionFilter(value)}
                        className={cn(
                            'flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm cursor-pointer',
                            active
                                ? 'border-accent text-accent bg-accent-highlight-secondary'
                                : 'border-primary bg-surface-primary hover:border-accent'
                        )}
                        data-attr={`evaluation-overview-table-filter-${value ?? 'all'}`}
                    >
                        <span>{label}</span>
                        {value === 'any' ? (
                            <span className="rounded-full bg-danger px-1.5 text-xs font-semibold text-white">
                                {count}
                            </span>
                        ) : (
                            <span className={cn('text-xs', active ? 'text-accent' : 'text-secondary')}>{count}</span>
                        )}
                    </button>
                )
            })}
        </div>
    )
}
