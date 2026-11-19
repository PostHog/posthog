import { useActions, useValues } from 'kea'

import { IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { teamLogic } from 'scenes/teamLogic'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import {
    QuickFilterKey,
    applyQuickFilter,
    internalUserFilters,
    quickFilterApplied,
    removeQuickFilter,
} from './evaluationQuickFilters'
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
    const applied = (key: QuickFilterKey): boolean => quickFilterApplied(key, evaluation.conditions, testAccountFilters)
    const disabledReason = (key: QuickFilterKey): string | undefined => {
        // A generation judge skips errored generations without grading them. Trace and session judges grade the
        // whole transcript, errors included, so the filter stays useful there.
        if (
            key === 'errors' &&
            !applied(key) &&
            evaluation.evaluation_type === 'llm_judge' &&
            evaluation.target === 'generation'
        ) {
            return 'The LLM judge skips generations with errors, so this would leave it nothing to grade.'
        }
        if (key === 'sample' && applied(key)) {
            return 'Already set. Change the percentage below.'
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
                        active: applied(key),
                        sideIcon: applied(key) ? <IconCheck /> : undefined,
                        onClick: () =>
                            setTriggerConditions(
                                (applied(key) ? removeQuickFilter : applyQuickFilter)(
                                    key,
                                    evaluation.conditions,
                                    testAccountFilters
                                )
                            ),
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
