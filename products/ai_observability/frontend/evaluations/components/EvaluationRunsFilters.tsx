import { useActions, useValues } from 'kea'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationRunsFilter } from '../types'

interface FilterOption {
    value: EvaluationRunsFilter
    label: string
}

const BASE_FILTER_OPTIONS: FilterOption[] = [
    { value: 'all', label: 'All' },
    { value: 'pass', label: 'Passing' },
    { value: 'fail', label: 'Failing' },
]

const NA_FILTER_OPTION: FilterOption = { value: 'na', label: 'N/A' }

export function EvaluationRunsFilters(): JSX.Element | null {
    const { evaluation, runsSummary, evaluationRunsFilter } = useValues(llmEvaluationLogic)
    const { setEvaluationRunsFilter } = useActions(llmEvaluationLogic)

    if (!runsSummary || runsSummary.total === 0) {
        return null
    }

    return (
        <LemonSegmentedButton
            value={evaluationRunsFilter}
            onChange={(value) => {
                setEvaluationRunsFilter(value, evaluationRunsFilter)
            }}
            options={[...BASE_FILTER_OPTIONS, ...(evaluation?.output_config?.allows_na ? [NA_FILTER_OPTION] : [])]}
            size="small"
            // pinned: autocapture data-attr - existing dashboards depend on it
            data-attr="llma-evaluation-summary-filter"
        />
    )
}
