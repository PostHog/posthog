import { useValues } from 'kea'
import { useId } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    CATEGORICAL_SELECTION_MODE_OPTIONS,
    formatKindLabel,
    formatNumericInputValue,
    getIntegerInputValue,
    getNumericInputValue,
    getScoreDefinitionOptionKey,
    type ScoreDefinitionDraft,
} from './scoreDefinitionModalUtils'

export interface ScoreDefinitionFormProps {
    draft: ScoreDefinitionDraft
    isNew: boolean
    disabled: boolean
    setDraftField: (field: keyof ScoreDefinitionDraft, value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]) => void
    updateOptionLabel: (index: number, value: string) => void
    addOption: () => void
    removeOption: (index: number) => void
}

export function ScoreDefinitionForm({
    draft,
    isNew,
    disabled,
    setDraftField,
    updateOptionLabel,
    addOption,
    removeOption,
}: ScoreDefinitionFormProps): JSX.Element {
    const id = useId()
    const { featureFlags } = useValues(featureFlagLogic)
    const disabledReason = disabled ? 'Editing is unavailable right now' : undefined
    const threshold = getNumericInputValue(draft.numericPassingThreshold)

    return (
        <div className="space-y-6 @container/scorer-form">
            <section className="space-y-4" aria-labelledby={`${id}-details`}>
                <h3 id={`${id}-details`} className="mb-0">
                    Details
                </h3>
                <LemonField.Pure label="Name" htmlFor={`${id}-name`}>
                    <LemonInput
                        id={`${id}-name`}
                        value={draft.name}
                        onChange={(value) => setDraftField('name', value)}
                        disabled={disabled}
                        placeholder="e.g. Answer quality"
                        data-attr="llma-scorer-name-input"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Description (optional)" htmlFor={`${id}-description`}>
                    <LemonTextArea
                        id={`${id}-description`}
                        value={draft.description}
                        onChange={(value) => setDraftField('description', value)}
                        disabled={disabled}
                        placeholder="What does this scorer measure?"
                        data-attr="llma-scorer-description-input"
                    />
                </LemonField.Pure>
            </section>

            <LemonDivider />

            <section className="space-y-4" aria-labelledby={`${id}-format`}>
                <h3 id={`${id}-format`} className="mb-0">
                    Score format
                </h3>
                <LemonField.Pure
                    label="Kind"
                    htmlFor={isNew ? `${id}-kind` : undefined}
                    help={isNew ? undefined : 'The kind stays the same across scorer versions.'}
                >
                    {isNew ? (
                        <LemonSelect
                            id={`${id}-kind`}
                            value={draft.kind}
                            onChange={(value) => setDraftField('kind', value)}
                            options={[
                                { label: 'Categorical', value: 'categorical' },
                                { label: 'Numeric', value: 'numeric' },
                                { label: 'Boolean', value: 'boolean' },
                            ]}
                            disabledReason={disabledReason}
                            data-attr="llma-scorer-kind-select"
                        />
                    ) : (
                        <LemonTag type="muted" className="self-start">
                            {formatKindLabel(draft.kind)}
                        </LemonTag>
                    )}
                </LemonField.Pure>

                {draft.kind === 'numeric' && (
                    <>
                        <div className="grid gap-4 @min-[36rem]/scorer-form:grid-cols-3">
                            {(
                                [
                                    ['numericMin', 'Minimum (optional)'],
                                    ['numericMax', 'Maximum (optional)'],
                                    ['numericStep', 'Increment (optional)'],
                                ] as const
                            ).map(([field, label]) => (
                                <LemonField.Pure key={field} label={label} htmlFor={`${id}-${field}`}>
                                    <LemonInput
                                        id={`${id}-${field}`}
                                        type="number"
                                        value={getNumericInputValue(draft[field])}
                                        onChange={(value) => setDraftField(field, formatNumericInputValue(value))}
                                        disabled={disabled}
                                        placeholder="Not set"
                                        step="any"
                                    />
                                </LemonField.Pure>
                            ))}
                        </div>
                        <p className="text-sm text-muted mb-0">
                            Bounds are inclusive. The increment guides manual scoring, for example 1 or 0.5.
                        </p>
                    </>
                )}

                {draft.kind === 'boolean' && (
                    <div className="grid gap-4 @min-[30rem]/scorer-form:grid-cols-2">
                        {(
                            [
                                ['trueLabel', 'True label (optional)', 'True'],
                                ['falseLabel', 'False label (optional)', 'False'],
                            ] as const
                        ).map(([field, label, placeholder]) => (
                            <LemonField.Pure key={field} label={label} htmlFor={`${id}-${field}`}>
                                <LemonInput
                                    id={`${id}-${field}`}
                                    value={draft[field]}
                                    onChange={(value) => setDraftField(field, value)}
                                    placeholder={placeholder}
                                    disabled={disabled}
                                />
                            </LemonField.Pure>
                        ))}
                    </div>
                )}

                {draft.kind === 'categorical' && (
                    <>
                        <div className="grid gap-4 @min-[36rem]/scorer-form:grid-cols-3">
                            <LemonField.Pure label="Selection mode" htmlFor={`${id}-selection-mode`}>
                                <LemonSelect
                                    id={`${id}-selection-mode`}
                                    value={draft.selectionMode}
                                    onChange={(value) => setDraftField('selectionMode', value)}
                                    options={CATEGORICAL_SELECTION_MODE_OPTIONS}
                                    disabledReason={disabledReason}
                                    data-attr="llma-scorer-selection-mode"
                                />
                            </LemonField.Pure>
                            {draft.selectionMode === 'multiple' &&
                                (
                                    [
                                        ['categoricalMinSelections', 'Minimum selections'],
                                        ['categoricalMaxSelections', 'Maximum selections'],
                                    ] as const
                                ).map(([field, label]) => (
                                    <LemonField.Pure key={field} label={label} htmlFor={`${id}-${field}`}>
                                        <LemonInput
                                            id={`${id}-${field}`}
                                            type="number"
                                            value={getIntegerInputValue(draft[field])}
                                            onChange={(value) => setDraftField(field, formatNumericInputValue(value))}
                                            min={1}
                                            max={draft.options.length}
                                            step={1}
                                            placeholder="Not set"
                                            disabled={disabled}
                                        />
                                    </LemonField.Pure>
                                ))}
                        </div>
                        <div className="space-y-3">
                            {draft.options.map((option, index) => (
                                <LemonField.Pure
                                    key={`${index}-${option.key}`}
                                    label={`Option ${index + 1}`}
                                    htmlFor={`${id}-option-${index}`}
                                >
                                    <div className="flex items-start gap-2">
                                        <LemonInput
                                            id={`${id}-option-${index}`}
                                            className="flex-1 min-w-0"
                                            placeholder="Option label"
                                            value={option.label}
                                            onChange={(value) => updateOptionLabel(index, value)}
                                            disabled={disabled}
                                        />
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            onClick={() => removeOption(index)}
                                            disabledReason={
                                                disabledReason ||
                                                (draft.options.length <= 1 ? 'Keep at least one option' : undefined)
                                            }
                                            data-attr="llma-scorer-remove-option"
                                        >
                                            Remove
                                        </LemonButton>
                                    </div>
                                </LemonField.Pure>
                            ))}
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={addOption}
                                disabledReason={disabledReason}
                                data-attr="llma-scorer-add-option"
                            >
                                Add option
                            </LemonButton>
                        </div>
                    </>
                )}
            </section>

            {featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] && (
                <>
                    <LemonDivider />
                    <section className="space-y-4" aria-labelledby={`${id}-passing`}>
                        <div className="space-y-1">
                            <h3 id={`${id}-passing`} className="mb-0">
                                Passing rule
                            </h3>
                            <p className="text-sm text-muted mb-0">
                                Choose which results count as passes in offline evaluations. The stored scores stay the
                                same.
                            </p>
                        </div>
                        {draft.kind === 'boolean' ? (
                            <>
                                <LemonField.Pure label="Passing value" htmlFor={`${id}-boolean-passing`}>
                                    <LemonSelect
                                        id={`${id}-boolean-passing`}
                                        value={draft.booleanPassing}
                                        onChange={(value) => setDraftField('booleanPassing', value)}
                                        options={[
                                            { value: 'true', label: 'True means pass' },
                                            { value: 'false', label: 'False means pass' },
                                        ]}
                                        disabledReason={disabledReason}
                                        data-attr="llma-scorer-boolean-passing"
                                    />
                                </LemonField.Pure>
                                <div className="flex flex-wrap gap-2" aria-label="Result preview">
                                    {(['true', 'false'] as const).map((value) => {
                                        const passing = draft.booleanPassing === value
                                        const label =
                                            value === 'true'
                                                ? draft.trueLabel.trim() || 'True'
                                                : draft.falseLabel.trim() || 'False'
                                        return (
                                            <LemonTag
                                                key={value}
                                                type={passing ? 'success' : 'danger'}
                                                icon={passing ? <IconCheck /> : <IconX />}
                                                wrap
                                            >
                                                {`${label}${passing ? ' · Pass' : ' · Fail'}`}
                                            </LemonTag>
                                        )
                                    })}
                                </div>
                            </>
                        ) : draft.kind === 'categorical' ? (
                            <>
                                <LemonSwitch
                                    label="Set a passing rule"
                                    checked={draft.categoricalPassingEnabled}
                                    onChange={(value) => setDraftField('categoricalPassingEnabled', value)}
                                    disabledReason={disabledReason}
                                    data-attr="llma-scorer-categorical-passing-rule"
                                />
                                {draft.categoricalPassingEnabled && (
                                    <LemonField.Pure label="Passing categories">
                                        <div className="flex flex-col gap-2">
                                            {draft.options.map((option, index) => {
                                                const key = getScoreDefinitionOptionKey(option)
                                                return (
                                                    <LemonCheckbox
                                                        key={index}
                                                        label={option.label || 'Unnamed category'}
                                                        checked={draft.categoricalPassingCategories.includes(key)}
                                                        disabled={disabled || !key}
                                                        onChange={(checked) =>
                                                            setDraftField(
                                                                'categoricalPassingCategories',
                                                                checked
                                                                    ? [...draft.categoricalPassingCategories, key]
                                                                    : draft.categoricalPassingCategories.filter(
                                                                          (category) => category !== key
                                                                      )
                                                            )
                                                        }
                                                    />
                                                )
                                            })}
                                        </div>
                                        <p className="text-sm text-muted mb-0">
                                            Every selected category must be marked as passing. Existing results keep
                                            their scorer version's rule.
                                        </p>
                                    </LemonField.Pure>
                                )}
                            </>
                        ) : (
                            <>
                                <LemonSwitch
                                    label="Set a passing rule"
                                    checked={draft.numericPassingEnabled}
                                    onChange={(value) => setDraftField('numericPassingEnabled', value)}
                                    disabledReason={disabledReason}
                                    data-attr="llma-scorer-numeric-passing-rule"
                                />
                                {draft.numericPassingEnabled && (
                                    <>
                                        <div className="grid gap-4 @min-[30rem]/scorer-form:grid-cols-2">
                                            <LemonField.Pure label="Pass when score is" htmlFor={`${id}-operator`}>
                                                <LemonSelect
                                                    id={`${id}-operator`}
                                                    value={draft.numericPassingOperator}
                                                    options={[
                                                        { value: 'gte', label: 'At least (≥)' },
                                                        { value: 'lte', label: 'At most (≤)' },
                                                    ]}
                                                    onChange={(value) => setDraftField('numericPassingOperator', value)}
                                                    disabledReason={disabledReason}
                                                    data-attr="llma-scorer-numeric-operator"
                                                />
                                            </LemonField.Pure>
                                            <LemonField.Pure label="Threshold" htmlFor={`${id}-threshold`}>
                                                <LemonInput
                                                    id={`${id}-threshold`}
                                                    type="number"
                                                    value={threshold}
                                                    onChange={(value) =>
                                                        setDraftField(
                                                            'numericPassingThreshold',
                                                            formatNumericInputValue(value)
                                                        )
                                                    }
                                                    min={getNumericInputValue(draft.numericMin)}
                                                    max={getNumericInputValue(draft.numericMax)}
                                                    step="any"
                                                    placeholder="Enter a threshold"
                                                    disabled={disabled}
                                                    data-attr="llma-scorer-numeric-threshold"
                                                />
                                            </LemonField.Pure>
                                        </div>
                                        {threshold !== undefined && (
                                            <div className="flex flex-wrap gap-2" aria-label="Result preview">
                                                <LemonTag type="success" icon={<IconCheck />}>
                                                    {`${draft.numericPassingOperator === 'gte' ? '≥' : '≤'} ${threshold} · Pass`}
                                                </LemonTag>
                                                <LemonTag type="danger" icon={<IconX />}>
                                                    {`${draft.numericPassingOperator === 'gte' ? '<' : '>'} ${threshold} · Fail`}
                                                </LemonTag>
                                            </div>
                                        )}
                                    </>
                                )}
                            </>
                        )}
                        {draft.kind === 'numeric' && !draft.numericPassingEnabled && (
                            <p className="text-sm text-muted mb-0">Scores stay neutral without a passing rule.</p>
                        )}
                    </section>
                </>
            )}
        </div>
    )
}
