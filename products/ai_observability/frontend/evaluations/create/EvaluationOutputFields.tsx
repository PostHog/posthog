import { useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { DecisionThresholdInput } from '../components/DecisionThresholdInput'
import { booleanOutputConfigError, decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationCategoryEditor } from './EvaluationCategoryEditor'
import { EvaluationScoreOutput } from './EvaluationScoreOutput'

type ReturnShape = 'boolean' | 'numeric' | 'categorical' | 'categorical_multiple'

/** What each run returns, read as one sentence, and which answers count as a pass. */
export function EvaluationOutputFields(): JSX.Element | null {
    const { evaluation, originalEvaluation, numericBoundsRequired, usesDecisionModel, isNewEvaluation } =
        useValues(llmEvaluationLogic)
    const { setOutputType, patchOutputConfig, setAllowsNA, setTrueIsFailure } = useActions(llmEvaluationLogic)

    // Sentiment always returns positive, neutral, or negative, which the method hint already says.
    if (!evaluation || evaluation.evaluation_type === 'sentiment') {
        return null
    }
    const config = evaluation.output_config
    const outputType = evaluation.output_type
    const shape: ReturnShape =
        outputType === 'categorical' && config.selection_mode === 'multiple'
            ? 'categorical_multiple'
            : (outputType as ReturnShape)
    const setShape = (next: ReturnShape): void => {
        const nextType = next === 'categorical_multiple' ? 'categorical' : next
        if (nextType !== outputType) {
            setOutputType(nextType)
        }
        if (nextType === 'categorical') {
            patchOutputConfig({ selection_mode: next === 'categorical_multiple' ? 'multiple' : 'single' })
        }
    }
    const usesThreshold = evaluation.evaluation_type === 'llm_judge' && usesDecisionModel && outputType === 'boolean'
    const bound = (field: 'min' | 'max'): JSX.Element => (
        <LemonInput
            type="number"
            size="small"
            className="w-20"
            value={config[field] ?? undefined}
            onChange={(value) => patchOutputConfig({ [field]: Number.isFinite(value) ? value : null })}
            placeholder={numericBoundsRequired ? field : 'any'}
            aria-label={field === 'min' ? 'Lowest score' : 'Highest score'}
            data-attr={`llma-evaluation-numeric-${field}`}
        />
    )

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-semibold">Return</span>
                <LemonSelect<ReturnShape>
                    size="small"
                    value={shape}
                    onChange={setShape}
                    options={(
                        [
                            { value: 'boolean', label: 'true or false' },
                            { value: 'numeric', label: 'a score' },
                            { value: 'categorical', label: 'one category' },
                            { value: 'categorical_multiple', label: 'several categories' },
                        ] as const
                    ).map((option) => ({
                        ...option,
                        // Past results keep their type, so a saved evaluation can only switch between category modes.
                        disabledReason:
                            !isNewEvaluation &&
                            (option.value === 'categorical_multiple' ? 'categorical' : option.value) !== outputType
                                ? 'Create a new evaluation to change what it returns.'
                                : undefined,
                    }))}
                    data-attr="llma-evaluation-output-type"
                />
                {outputType === 'boolean' && (
                    <>
                        <span>where true counts as a</span>
                        <LemonSegmentedButton
                            size="small"
                            value={config.true_is_failure ? 'fail' : 'pass'}
                            onChange={(value) => setTrueIsFailure(value === 'fail')}
                            options={[
                                { value: 'pass', label: 'Pass', 'data-attr': 'llma-evaluation-true-is-pass' },
                                { value: 'fail', label: 'Fail', 'data-attr': 'llma-evaluation-true-is-failure' },
                            ]}
                        />
                    </>
                )}
                {outputType === 'numeric' && (
                    <>
                        <span>from</span>
                        {bound('min')}
                        <span>to</span>
                        {bound('max')}
                    </>
                )}
            </div>
            {usesThreshold && (
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span>Answer true when the probability is at least</span>
                        <DecisionThresholdInput />
                    </div>
                    {booleanOutputConfigError(config) && (
                        <span className="text-xs text-danger">{booleanOutputConfigError(config)}</span>
                    )}
                </div>
            )}
            {outputType === 'numeric' && <EvaluationScoreOutput config={config} onChange={patchOutputConfig} />}
            {outputType === 'categorical' && (
                <EvaluationCategoryEditor
                    config={config}
                    onChange={patchOutputConfig}
                    showKeys={evaluation.evaluation_type === 'hog'}
                    storedKeys={
                        isNewEvaluation
                            ? []
                            : (originalEvaluation?.output_config.options ?? []).map((option) => option.key)
                    }
                />
            )}
            {usesDecisionModel && evaluation.evaluation_type === 'llm_judge' && (
                <p className="mb-0 text-xs text-secondary">{decisionModelHint(outputType)}</p>
            )}
            <LemonCheckbox
                label={`${
                    evaluation.evaluation_type === 'hog' ? 'The code' : 'The judge'
                } can answer not applicable, when the check does not apply to a run`}
                checked={config.allows_na ?? false}
                onChange={setAllowsNA}
                data-attr="llma-evaluation-create-allows-na"
            />
        </div>
    )
}
