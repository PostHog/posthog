import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, Link } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { RE2_DOCS_LINK } from 'lib/utils/regexp'

import {
    MAX_EVALUATION_INPUT_TRANSFORMATIONS,
    MAX_EVALUATION_INPUT_TRANSFORMATION_PATTERN_LENGTH,
    MAX_EVALUATION_INPUT_TRANSFORMATION_REPLACEMENT_LENGTH,
    inputTransformationPatternError,
} from '../evaluationInputTransformations'
import type { EvaluationInputTransformation } from '../types'

export interface EvaluationInputPreprocessingProps {
    transformations: EvaluationInputTransformation[]
    onAdd: () => void
    onUpdate: (index: number, patch: Partial<EvaluationInputTransformation>) => void
    onRemove: (index: number) => void
    onMove: (index: number, direction: 'up' | 'down') => void
}

export function EvaluationInputPreprocessing({
    transformations,
    onAdd,
    onUpdate,
    onRemove,
    onMove,
}: EvaluationInputPreprocessingProps): JSX.Element {
    return (
        <div className="bg-bg-light border rounded p-6">
            <h3 className="text-lg font-semibold mb-2">Input preprocessing</h3>
            <p className="text-muted text-sm mb-4">
                Replace matching text before it is sent to the judge. Rules use{' '}
                <Link to={RE2_DOCS_LINK} target="_blank">
                    RE2 syntax
                </Link>{' '}
                and run from top to bottom. Stored traces stay unchanged.
            </p>

            <div className="space-y-3">
                {transformations.length === 0 ? (
                    <div className="border rounded p-4 text-muted text-sm">No preprocessing rules configured.</div>
                ) : (
                    transformations.map((transformation, index) => {
                        const patternError = inputTransformationPatternError(transformation.pattern)
                        return (
                            <div key={index} className="border rounded p-3 min-w-0">
                                <div className="grid grid-cols-1 @min-[48rem]/main-content:grid-cols-2 gap-3">
                                    <LemonField.Pure label="Regular expression" error={patternError ?? undefined}>
                                        <LemonInput
                                            value={transformation.pattern}
                                            onChange={(pattern) => onUpdate(index, { pattern })}
                                            placeholder="(?s)<context>.*?</context>"
                                            className="font-mono"
                                            status={patternError ? 'danger' : undefined}
                                            maxLength={MAX_EVALUATION_INPUT_TRANSFORMATION_PATTERN_LENGTH}
                                        />
                                    </LemonField.Pure>
                                    <LemonField.Pure label="Replacement (optional)">
                                        <LemonInput
                                            value={transformation.replacement ?? ''}
                                            onChange={(replacement) => onUpdate(index, { replacement })}
                                            placeholder="Leave empty to remove matches"
                                            maxLength={MAX_EVALUATION_INPUT_TRANSFORMATION_REPLACEMENT_LENGTH}
                                        />
                                    </LemonField.Pure>
                                </div>
                                <div className="flex flex-wrap justify-end gap-1 mt-2">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        icon={<IconArrowUp />}
                                        onClick={() => onMove(index, 'up')}
                                        disabledReason={index === 0 ? 'This rule is already first.' : undefined}
                                        tooltip="Move rule up"
                                        data-attr={`llma-evaluation-move-input-transformation-up-${index}`}
                                    />
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        icon={<IconArrowDown />}
                                        onClick={() => onMove(index, 'down')}
                                        disabledReason={
                                            index === transformations.length - 1
                                                ? 'This rule is already last.'
                                                : undefined
                                        }
                                        tooltip="Move rule down"
                                        data-attr={`llma-evaluation-move-input-transformation-down-${index}`}
                                    />
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        status="danger"
                                        icon={<IconTrash />}
                                        onClick={() => onRemove(index)}
                                        tooltip="Delete rule"
                                        data-attr={`llma-evaluation-remove-input-transformation-${index}`}
                                    />
                                </div>
                            </div>
                        )
                    })
                )}
            </div>

            <LemonButton
                type="secondary"
                size="small"
                icon={<IconPlus />}
                onClick={onAdd}
                disabledReason={
                    transformations.length >= MAX_EVALUATION_INPUT_TRANSFORMATIONS
                        ? `You can add up to ${MAX_EVALUATION_INPUT_TRANSFORMATIONS} rules.`
                        : undefined
                }
                className="mt-3"
                data-attr="llma-evaluation-add-input-transformation"
            >
                Add rule
            </LemonButton>
        </div>
    )
}
