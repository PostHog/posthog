import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { teamLogic } from 'scenes/teamLogic'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { QuickFilterKey, applyQuickFilter, internalUserFilters, quickFilterApplied } from './evaluationQuickFilters'
import { EvaluationTriggers } from './EvaluationTriggers'

const QUICK_FILTERS: { key: QuickFilterKey; label: string }[] = [
    { key: 'internal', label: 'Exclude internal users' },
    { key: 'errors', label: 'Only errors' },
    { key: 'expensive', label: 'Only calls over $0.01' },
    { key: 'sample', label: 'Sample 10%' },
]

export function EvaluationTriggersPanel(): JSX.Element | null {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setTriggerConditions } = useActions(llmEvaluationLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!evaluation) {
        return null
    }
    const testAccountFilters = currentTeam?.test_account_filters ?? []
    const usableInternalFilters = internalUserFilters(testAccountFilters).length
    const disabledReason = (key: QuickFilterKey): string | undefined => {
        // A generation judge skips errored generations without grading them. Trace and session judges grade the
        // whole transcript, errors included, so the filter stays useful there.
        if (key === 'errors' && evaluation.evaluation_type === 'llm_judge' && evaluation.target === 'generation') {
            return 'The LLM judge skips generations with errors, so this would leave it nothing to grade.'
        }
        if (quickFilterApplied(key, evaluation.conditions, testAccountFilters)) {
            return 'Already added'
        }
        if (key === 'internal' && usableInternalFilters === 0) {
            return 'Add internal and test user filters in project settings first.'
        }
        return undefined
    }
    const tooltip = (key: QuickFilterKey): string | undefined =>
        key === 'internal' && usableInternalFilters < testAccountFilters.length
            ? "Cohort and group filters from project settings can't be used here, so they're left out."
            : undefined

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h4 className="mb-0 text-sm font-semibold">Choose the traffic</h4>
                <LemonMenu
                    items={QUICK_FILTERS.map(({ key, label }) => ({
                        label,
                        onClick: () =>
                            setTriggerConditions(applyQuickFilter(key, evaluation.conditions, testAccountFilters)),
                        disabledReason: disabledReason(key),
                        tooltip: tooltip(key),
                        'data-attr': `llma-evaluation-quick-filter-${key}`,
                    }))}
                >
                    <LemonButton type="tertiary" size="xsmall" sideIcon={<IconChevronDown />}>
                        <span className="text-xs font-normal text-secondary">Quick filters</span>
                    </LemonButton>
                </LemonMenu>
            </div>
            <EvaluationTriggers />
            {evaluation.target !== 'generation' && (
                <p className="mb-0 text-xs text-secondary">
                    A {evaluation.target} matches when one of its generations does.
                </p>
            )}
        </div>
    )
}
