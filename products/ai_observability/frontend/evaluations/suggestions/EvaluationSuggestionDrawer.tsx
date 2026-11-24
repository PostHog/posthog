import { useActions, useValues } from 'kea'

import { LemonDivider } from '@posthog/lemon-ui'

import { humanFriendlyCurrency, humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvalSuggestionApi } from '../../generated/api.schemas'
import { EvaluationDetailDrawer } from '../components/EvaluationDetailDrawer'
import { EvaluationDrawerSection } from '../components/EvaluationDrawerSection'
import { EvaluationDrawerStat } from '../components/EvaluationDrawerStat'
import { TraceSampleRow } from '../components/TraceSampleRow'
import { TraceSampleRowSkeleton } from '../components/TraceSampleRowSkeleton'
import { EvaluationSuggestionActions } from './EvaluationSuggestionActions'
import { EvaluationSuggestionDetails } from './EvaluationSuggestionDetails'
import { evaluationSuggestionsLogic } from './evaluationSuggestionsLogic'
import { suggestionKindLabel } from './suggestionKind'
import { unitNoun } from './units'

interface SuggestionStat {
    label: string
    value: string
    detail: string
}

function weeklyCost(usd: number | null): string {
    if (usd === null) {
        return 'Per run'
    }
    return usd < 0.01 ? 'Under $0.01/wk' : `${humanFriendlyCurrency(usd)}/wk`
}

/** The numbers behind a suggestion: how much of the sample it flagged, how often it would run, and what it costs. */
function suggestionStats(suggestion: EvalSuggestionApi): SuggestionStat[] {
    const stats: SuggestionStat[] = []
    const { measured_failure_rate: rate, sample_size: size, rollout_percentage: rollout } = suggestion
    if (rate !== null) {
        stats.push({
            label: 'Flagged',
            value: `${humanFriendlyNumber(rate * 100, 1)}%`,
            detail: size ? `${Math.round(rate * size)} of ${size} sampled` : suggestion.observation_scope,
        })
    }
    if (suggestion.kind !== 'new_hog' && suggestion.kind !== 'new_llm_judge') {
        return stats
    }
    const target = typeof suggestion.draft.target === 'string' ? suggestion.draft.target : undefined
    const sampling = rollout >= 100 ? 'Every match' : `${humanFriendlyNumber(rollout)}% of matches`
    stats.push(
        suggestion.estimated_weekly_runs !== null
            ? {
                  label: 'Volume',
                  value: `${humanFriendlyNumber(suggestion.estimated_weekly_runs)}/wk`,
                  detail: sampling,
              }
            : { label: 'Sampling', value: sampling, detail: `Of matching ${unitNoun(target, 2)}` }
    )
    const isJudge = suggestion.draft.evaluation_type === 'llm_judge'
    stats.push({
        label: 'AI provider cost',
        value: isJudge ? weeklyCost(suggestion.estimated_weekly_cost_usd) : 'None',
        detail: isJudge ? 'Uses your API key' : 'Runs as code',
    })
    return stats
}

/** A suggestion in full: what was noticed, the numbers behind it, what the eval checks, and the traces it flags. */
export function EvaluationSuggestionDrawer(): JSX.Element | null {
    const { openedSuggestion: suggestion, evidenceSamples } = useValues(evaluationSuggestionsLogic)
    const { closeSuggestion, openExamples } = useActions(evaluationSuggestionsLogic)

    if (!suggestion) {
        return null
    }
    const samples = evidenceSamples[suggestion.id]
    const stats = suggestionStats(suggestion)
    const proposesEval = suggestion.kind === 'new_hog' || suggestion.kind === 'new_llm_judge'

    return (
        <EvaluationDetailDrawer
            title={suggestionKindLabel(suggestion)}
            actions={<EvaluationSuggestionActions suggestion={suggestion} />}
            onClose={closeSuggestion}
            aria-label="Suggested eval"
            data-attr="eval-suggestion-drawer"
        >
            <div className="@container flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <h3 className="m-0 text-lg font-semibold">{suggestion.headline}</h3>
                    <p className="m-0 text-sm text-secondary">{suggestion.outcome}</p>
                </div>
                {stats.length > 0 && (
                    <div className="grid grid-cols-1 gap-2 @min-[30rem]:grid-cols-3">
                        {stats.map((stat) => (
                            <EvaluationDrawerStat key={stat.label} {...stat} />
                        ))}
                    </div>
                )}
                <LemonDivider className="my-0" />
                <EvaluationDrawerSection title={proposesEval ? 'What it checks' : 'What we found'}>
                    <EvaluationSuggestionDetails suggestion={suggestion} />
                </EvaluationDrawerSection>
                {suggestion.evidence.length > 0 && (
                    <>
                        <LemonDivider className="my-0" />
                        <EvaluationDrawerSection
                            title="Sample traces"
                            subtitle={
                                proposesEval ? 'From the sample, the traces this eval would flag' : 'From the sample'
                            }
                        >
                            <div className="overflow-hidden rounded border border-primary divide-y divide-primary">
                                {samples
                                    ? suggestion.evidence.map((item) => (
                                          <TraceSampleRow
                                              key={item.trace_id}
                                              sample={samples[item.trace_id] ?? null}
                                              timestamp={null}
                                              note={item.reason}
                                              onOpen={() => openExamples(suggestion, item.trace_id)}
                                              data-attr="eval-suggestion-examples"
                                          />
                                      ))
                                    : suggestion.evidence.map((item) => <TraceSampleRowSkeleton key={item.trace_id} />)}
                            </div>
                        </EvaluationDrawerSection>
                    </>
                )}
            </div>
        </EvaluationDetailDrawer>
    )
}
