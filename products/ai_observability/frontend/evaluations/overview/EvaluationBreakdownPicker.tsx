import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { evaluationDetailResultsLogic } from './evaluationDetailResultsLogic'

/** Properties every result event carries. The prompt ones are copied from the generation the evaluation scored. */
const BREAKDOWN_OPTIONS = [
    { value: '$ai_prompt_version', label: 'Prompt version' },
    { value: '$ai_prompt_name', label: 'Prompt name' },
    { value: '$ai_evaluation_model', label: 'Judge model', judgeOnly: true },
    { value: '$ai_evaluation_trigger', label: 'Live or backfill' },
]

export function EvaluationBreakdownPicker({ evaluationId }: { evaluationId: string }): JSX.Element {
    const logic = evaluationDetailResultsLogic({ evaluationId })
    const { breakdownProperty, breakdownSeriesLoading } = useValues(logic)
    const { setBreakdownProperty } = useActions(logic)
    const { originalEvaluation } = useValues(llmEvaluationLogic({ evaluationId }))

    return (
        <LemonSelect
            size="small"
            value={breakdownProperty}
            onChange={setBreakdownProperty}
            loading={breakdownSeriesLoading}
            options={[
                { value: null, label: 'No breakdown' },
                ...BREAKDOWN_OPTIONS.filter(
                    (option) => !option.judgeOnly || originalEvaluation?.evaluation_type === 'llm_judge'
                ).map(({ value, label }) => ({ value, label: `By ${label.toLowerCase()}` })),
            ]}
            data-attr="llma-evaluation-results-breakdown"
        />
    )
}
