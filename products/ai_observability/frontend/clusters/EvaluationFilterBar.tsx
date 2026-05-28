import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect } from '@posthog/lemon-ui'

import { clustersLogic } from './clustersLogic'
import { EvaluationVerdict } from './traceSummaryLoader'

const VERDICT_ORDER: EvaluationVerdict[] = ['pass', 'fail', 'n/a', 'unknown']

/**
 * Eval-only post-hoc filter row. Lets the user narrow the scatter, distribution bar, and
 * cluster cards down to a chosen evaluator and/or verdict subset without re-running clustering.
 *
 * The filter is purely client-side — `clustersLogic` keeps a per-item (evaluatorName, verdict)
 * lookup loaded once per run, and a single `evalFilterPredicate` selector drives every
 * downstream view, so they can't drift.
 */
export function EvaluationFilterBar(): JSX.Element | null {
    const {
        clusteringLevel,
        availableEvaluatorNames,
        availableVerdictCounts,
        evalFilterEvaluatorNames,
        evalFilterVerdicts,
        evalFiltersActive,
        filteredItemCount,
        totalItemCount,
        evaluationItemAttributes,
    } = useValues(clustersLogic)
    const { setEvalEvaluatorNamesFilter, setEvalVerdictsFilter, clearEvalFilters } = useActions(clustersLogic)

    if (clusteringLevel !== 'evaluation') {
        return null
    }
    // Don't render until we have something to filter by — keeps the row from flashing in empty.
    if (Object.keys(evaluationItemAttributes).length === 0) {
        return null
    }

    const evaluatorOptions = availableEvaluatorNames.map(({ name, count }) => ({
        key: name,
        label: `${name} (${count})`,
    }))

    const toggleVerdict = (v: EvaluationVerdict): void => {
        const next = evalFilterVerdicts.includes(v)
            ? evalFilterVerdicts.filter((x) => x !== v)
            : [...evalFilterVerdicts, v]
        setEvalVerdictsFilter(next)
    }

    return (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-4">
            <div className="flex items-center gap-2 flex-1 min-w-[280px]">
                <span className="text-sm text-muted shrink-0">Evaluations</span>
                <div className="flex-1 min-w-[200px]">
                    <LemonInputSelect
                        mode="multiple"
                        value={evalFilterEvaluatorNames}
                        onChange={(values) => setEvalEvaluatorNamesFilter(values)}
                        options={evaluatorOptions}
                        placeholder="All evaluations"
                        size="small"
                        allowCustomValues={false}
                        data-attr="clusters-eval-evaluator-filter"
                    />
                </div>
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm text-muted shrink-0">Verdict</span>
                <div className="flex items-center gap-1">
                    {VERDICT_ORDER.filter((v) => availableVerdictCounts[v] > 0).map((v) => {
                        const count = availableVerdictCounts[v]
                        const selected = evalFilterVerdicts.includes(v)
                        return (
                            <LemonButton
                                key={v}
                                size="xsmall"
                                type="secondary"
                                active={selected}
                                onClick={() => toggleVerdict(v)}
                                data-attr={`clusters-eval-verdict-filter-${v}`}
                            >
                                {v} <span className="text-muted ml-1">({count})</span>
                            </LemonButton>
                        )
                    })}
                </div>
            </div>

            <div className="flex items-center gap-2 ml-auto">
                <span className="text-xs text-muted whitespace-nowrap">
                    {evalFiltersActive
                        ? `${filteredItemCount} of ${totalItemCount} evaluations`
                        : `${totalItemCount} evaluations`}
                </span>
                {evalFiltersActive && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        onClick={() => clearEvalFilters()}
                        data-attr="clusters-eval-filter-clear"
                    >
                        Clear
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
