import { useActions, useValues } from 'kea'

import { IconList, IconListCheck, IconStar, IconThumbsUp } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { DecisionThresholdInput } from '../components/DecisionThresholdInput'
import { booleanOutputConfigError, decisionModelHint } from '../constants'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationCategoryEditor } from './EvaluationCategoryEditor'
import { EvaluationCategoryPassing } from './EvaluationCategoryPassing'
import { EvaluationChoiceCards } from './EvaluationChoiceCards'
import { EvaluationPassRatePreview } from './EvaluationPassRatePreview'
import { EvaluationScoreOutput } from './EvaluationScoreOutput'

type ReturnShape = 'boolean' | 'numeric' | 'categorical' | 'categorical_multiple'

export function EvaluationOutputFields(): JSX.Element | null {
    const { evaluation, originalEvaluation, numericBoundsRequired, usesDecisionModel, isNewEvaluation } =
        useValues(llmEvaluationLogic)
    const { setOutputType, patchOutputConfig, setAllowsNA, setTrueIsFailure } = useActions(llmEvaluationLogic)

    // Sentiment always returns positive, neutral, or negative, which its method card already says.
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
    // Past results keep their type, so a saved evaluation can only switch between category modes.
    const lockedReason = (value: ReturnShape): string | undefined =>
        !isNewEvaluation && (value === 'categorical_multiple' ? 'categorical' : value) !== outputType
            ? 'Create a new evaluation to change what it returns.'
            : undefined
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
        <div className="flex flex-col gap-6">
            <EvaluationChoiceCards<ReturnShape>
                label="What it returns"
                value={shape}
                onChange={setShape}
                dataAttr="llma-evaluation-output-type"
                options={[
                    {
                        value: 'boolean',
                        label: 'True or false',
                        description: 'A yes or no, like whether the answer cites a source.',
                        icon: <IconThumbsUp />,
                        disabledReason: lockedReason('boolean'),
                    },
                    {
                        value: 'numeric',
                        label: 'Score',
                        description: 'A number in a range you set, like 1 to 5.',
                        icon: <IconStar />,
                        disabledReason: lockedReason('numeric'),
                    },
                    {
                        value: 'categorical',
                        label: 'One category',
                        description: 'One label from your list, like Resolved or Handed off.',
                        icon: <IconList />,
                        disabledReason: lockedReason('categorical'),
                    },
                    {
                        value: 'categorical_multiple',
                        label: 'Several categories',
                        description: 'Every label from your list that fits the run.',
                        icon: <IconListCheck />,
                        disabledReason: lockedReason('categorical_multiple'),
                    },
                ]}
            />
            <div className="flex flex-col gap-3 empty:hidden">
                {usesThreshold && (
                    <div className="flex flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                            <span>It returns true when the probability is at least</span>
                            <DecisionThresholdInput />
                        </div>
                        {booleanOutputConfigError(config) && (
                            <span className="text-xs text-danger">{booleanOutputConfigError(config)}</span>
                        )}
                    </div>
                )}
                {outputType === 'numeric' && (
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span>Scores go from</span>
                        {bound('min')}
                        <span>to</span>
                        {bound('max')}
                    </div>
                )}
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
            </div>
            <div className="flex flex-col gap-0.5">
                <LemonCheckbox
                    label={'Accept a "doesn\'t apply" answer'}
                    checked={config.allows_na ?? false}
                    onChange={setAllowsNA}
                    data-attr="llma-evaluation-create-allows-na"
                />
                <span className="text-xs text-secondary pl-6">
                    Runs where the check doesn't apply count as neither a pass nor a fail.
                </span>
            </div>
            <div className="grid grid-cols-1 items-start gap-4 border-t pt-6 @min-[40rem]/evaluation:grid-cols-2">
                <div className="flex flex-col gap-3 min-w-0">
                    <div className="flex flex-col gap-1">
                        <h4 className="mb-0 flex items-center gap-2 text-sm font-semibold">
                            Pass rate
                            {outputType !== 'boolean' && (
                                <LemonTag size="small" type="muted">
                                    Optional
                                </LemonTag>
                            )}
                        </h4>
                        <p className="mb-0 text-xs text-secondary">
                            The share of runs that pass. The results page charts it, and reports tell you when it
                            changes.
                        </p>
                    </div>
                    {outputType === 'boolean' && (
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                            <span>A run passes when it returns</span>
                            <LemonSegmentedButton
                                size="small"
                                value={config.true_is_failure ? 'false' : 'true'}
                                onChange={(value) => setTrueIsFailure(value === 'false')}
                                options={[
                                    // pinned: data-attr values, because autocapture insights read them
                                    { value: 'true', label: 'true', 'data-attr': 'llma-evaluation-true-is-pass' },
                                    { value: 'false', label: 'false', 'data-attr': 'llma-evaluation-true-is-failure' },
                                ]}
                            />
                        </div>
                    )}
                    {outputType === 'numeric' && <EvaluationScoreOutput config={config} onChange={patchOutputConfig} />}
                    {outputType === 'categorical' && (
                        <EvaluationCategoryPassing config={config} onChange={patchOutputConfig} />
                    )}
                </div>
                <EvaluationPassRatePreview outputType={outputType} config={config} />
            </div>
        </div>
    )
}
