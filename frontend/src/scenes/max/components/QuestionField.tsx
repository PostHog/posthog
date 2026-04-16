import { useMemo, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider/LemonSlider'

import type { MultiQuestionFormField, MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { OptionSelector, type Option } from './OptionSelector'

interface QuestionFieldProps {
    question: MultiQuestionFormQuestion
    value: string | string[] | undefined
    onAnswer: (value: string | string[] | null) => void
    /** Called on each intermediate state change for multi_select (checkbox toggle, custom value add) */
    onChange: (value: string[]) => void
    /** Called when the user confirms a multi_select answer by clicking "Next" */
    onSubmit: () => void
    onSkip?: () => void
    submitLabel?: string
}

export function QuestionField({
    question,
    value,
    onAnswer,
    onChange,
    onSubmit,
    onSkip,
    submitLabel = 'Next',
}: QuestionFieldProps): JSX.Element {
    const fieldType = question.type ?? 'select'

    switch (fieldType) {
        case 'multi_select':
            return (
                <MultiSelectField
                    question={question}
                    value={value as string[] | undefined}
                    onChange={onChange}
                    onSubmit={onSubmit}
                    onSkip={onSkip}
                    submitLabel={submitLabel}
                />
            )
        case 'select':
        default:
            return (
                <SelectField
                    question={question}
                    value={value as string | undefined}
                    onAnswer={onAnswer}
                    onSkip={onSkip}
                    submitLabel={submitLabel}
                />
            )
    }
}

function SelectField({
    question,
    value,
    onAnswer,
    onSkip,
    submitLabel,
}: {
    question: MultiQuestionFormQuestion
    value: string | undefined
    onAnswer: (value: string | null) => void
    onSkip?: () => void
    submitLabel: string
}): JSX.Element {
    const options: Option[] = (question.options ?? []).map((option) => ({
        label: option.value,
        value: option.value,
        description: option.description,
    }))

    const allowCustomAnswer = question.allow_custom_answer !== false

    return (
        <OptionSelector
            options={options}
            onSelect={onAnswer}
            allowCustom={allowCustomAnswer}
            customPlaceholder="Type your answer..."
            onCustomSubmit={onAnswer}
            selectedValue={value}
            submitLabel={submitLabel}
            onSkip={onSkip}
        />
    )
}

function MultiSelectField({
    question,
    value,
    onChange,
    onSubmit,
    onSkip,
    submitLabel,
}: {
    question: MultiQuestionFormQuestion
    value: string[] | undefined
    onChange: (value: string[]) => void
    onSubmit: () => void
    onSkip?: () => void
    submitLabel: string
}): JSX.Element {
    const predefinedValues = useMemo(() => new Set((question.options ?? []).map((o) => o.value)), [question.options])
    const customValues = useMemo(() => (value ?? []).filter((v) => !predefinedValues.has(v)), [value, predefinedValues])

    const [customInput, setCustomInput] = useState('')
    const [showError, setShowError] = useState(false)

    const selected = value ?? []
    const allowCustomAnswer = question.allow_custom_answer !== false

    const handleToggle = (optionValue: string): void => {
        const next = selected.includes(optionValue)
            ? selected.filter((v) => v !== optionValue)
            : [...selected, optionValue]
        onChange(next)
        setShowError(false)
    }

    const handleAddCustom = (): void => {
        const trimmed = customInput.trim()
        if (!trimmed) {
            return
        }

        // If it matches a predefined option (case-insensitive), auto-check that instead
        const matchingPredefined = (question.options ?? []).find((o) => o.value.toLowerCase() === trimmed.toLowerCase())
        if (matchingPredefined) {
            if (!selected.includes(matchingPredefined.value)) {
                onChange([...selected, matchingPredefined.value])
            }
            setCustomInput('')
            setShowError(false)
            return
        }

        // If it matches an existing custom value (case-insensitive), auto-check that instead
        const matchingCustom = customValues.find((v) => v.toLowerCase() === trimmed.toLowerCase())
        if (matchingCustom) {
            if (!selected.includes(matchingCustom)) {
                onChange([...selected, matchingCustom])
            }
            setCustomInput('')
            setShowError(false)
            return
        }

        onChange([...selected, trimmed])
        setCustomInput('')
        setShowError(false)
    }

    const handleSubmit = (): void => {
        if (selected.length === 0) {
            setShowError(true)
            return
        }
        onSubmit()
    }

    return (
        <div className="flex flex-col gap-3">
            {(question.options ?? []).map((option) => (
                <LemonCheckbox
                    key={option.value}
                    checked={selected.includes(option.value)}
                    onChange={() => handleToggle(option.value)}
                    label={
                        <div>
                            <span className="font-medium">{option.value}</span>
                            {option.description && <span className="text-muted ml-1">— {option.description}</span>}
                        </div>
                    }
                />
            ))}
            {customValues.map((customValue) => (
                <LemonCheckbox
                    key={`custom-${customValue}`}
                    checked={selected.includes(customValue)}
                    onChange={() => handleToggle(customValue)}
                    label={<span className="font-medium">{customValue}</span>}
                />
            ))}
            {allowCustomAnswer && (
                <div className="flex gap-2 items-center">
                    <LemonInput
                        placeholder="Add your own option..."
                        fullWidth
                        size="small"
                        value={customInput}
                        onChange={setCustomInput}
                        onPressEnter={handleAddCustom}
                        className="flex-grow"
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        disabledReason={!customInput.trim() ? 'Type a value first' : undefined}
                        onClick={handleAddCustom}
                    >
                        Add
                    </LemonButton>
                </div>
            )}
            {showError && <p className="text-danger text-xs m-0">Select at least one option</p>}
            <div className="flex items-center justify-between gap-2">
                {onSkip && (
                    <LemonButton type="secondary" size="small" onClick={onSkip}>
                        Skip question
                    </LemonButton>
                )}
                <LemonButton type="primary" size="small" onClick={handleSubmit} className="self-start ml-auto">
                    {submitLabel}
                </LemonButton>
            </div>
        </div>
    )
}

export function isFieldValid(field: MultiQuestionFormField, value: string | string[] | undefined): boolean {
    if (value === undefined || value === '') {
        return !!field.optional
    }
    if (field.type === 'text') {
        return typeof value === 'string' && value.trim().length > 0
    }
    return true
}

// Multi-field question: renders multiple fields with a shared submit button

interface MultiFieldQuestionProps {
    question: MultiQuestionFormQuestion
    answers: Record<string, string | string[]>
    onFieldChange: (fieldId: string, value: string | string[]) => void
    onSubmit: () => void
    onSkip?: () => void
    submitLabel?: string
}

export function MultiFieldQuestion({
    question,
    answers,
    onFieldChange,
    onSubmit,
    onSkip,
    submitLabel = 'Next',
}: MultiFieldQuestionProps): JSX.Element {
    const fields = question.fields ?? []
    const allFieldsValid = fields.every((field) => isFieldValid(field, answers[field.id]))
    const [showErrors, setShowErrors] = useState(false)

    const handleSubmit = (): void => {
        if (!allFieldsValid) {
            setShowErrors(true)
            return
        }
        onSubmit()
    }

    return (
        <div className="flex flex-col gap-3">
            {fields.map((field) => {
                const fieldInvalid = showErrors && !isFieldValid(field, answers[field.id])
                return (
                    <div key={field.id} className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-secondary">
                            {field.label}
                            {field.optional && <span className="text-muted font-normal ml-1">(optional)</span>}
                        </label>
                        <MultiFieldInput
                            field={field}
                            value={answers[field.id]}
                            onChange={onFieldChange}
                            showError={fieldInvalid}
                        />
                        {fieldInvalid && <p className="text-danger text-xs m-0">This field is required</p>}
                    </div>
                )
            })}
            <div className="flex items-center justify-between gap-2">
                {onSkip && (
                    <LemonButton type="secondary" size="small" onClick={onSkip}>
                        Skip question
                    </LemonButton>
                )}
                <LemonButton type="primary" size="small" onClick={handleSubmit} className="self-end ml-auto">
                    {submitLabel}
                </LemonButton>
            </div>
        </div>
    )
}

function MultiFieldInput({
    field,
    value,
    onChange,
    showError,
}: {
    field: MultiQuestionFormField
    value: string | string[] | undefined
    onChange: (fieldId: string, value: string | string[]) => void
    showError?: boolean
}): JSX.Element {
    switch (field.type) {
        case 'dropdown': {
            const options = (field.options ?? []).map((opt) => ({
                value: opt.value,
                label: opt.value,
            }))
            return (
                <div className={showError ? '[&_.LemonButton]:border-danger' : undefined}>
                    <LemonSelect
                        options={options}
                        value={value as string | undefined}
                        onChange={(v) => v && onChange(field.id, v)}
                        placeholder="Select an option..."
                        fullWidth
                        size="small"
                    />
                </div>
            )
        }
        case 'text':
            return (
                <LemonInput
                    placeholder={field.placeholder ?? 'Type your answer...'}
                    fullWidth
                    size="small"
                    value={(value as string) ?? ''}
                    onChange={(v) => onChange(field.id, v)}
                    status={showError ? 'danger' : 'default'}
                />
            )
        case 'number':
            return (
                <LemonInput
                    type="number"
                    placeholder={field.placeholder ?? 'Enter a number...'}
                    fullWidth
                    size="small"
                    value={value !== undefined ? Number(value) : undefined}
                    onChange={(v) => {
                        if (v !== undefined && !isNaN(v)) {
                            onChange(field.id, String(v))
                        }
                    }}
                    min={field.min}
                    max={field.max}
                    step={field.step}
                    status={showError ? 'danger' : 'default'}
                />
            )
        case 'slider': {
            const min = field.min ?? 0
            const max = field.max ?? 100
            const step = field.step ?? 1
            const sliderVal = value ? Number(value) : min
            return (
                <div className="flex items-center gap-3">
                    <LemonSlider
                        value={sliderVal}
                        onChange={(v) => onChange(field.id, String(v))}
                        min={min}
                        max={max}
                        step={step}
                        className="flex-grow"
                    />
                    <span className="text-sm font-medium min-w-8 text-right">{sliderVal}</span>
                </div>
            )
        }
        case 'toggle':
            return (
                <LemonSwitch
                    checked={(value as string) === 'true'}
                    onChange={(v) => onChange(field.id, String(v))}
                    bordered
                />
            )
        default:
            return <span className="text-muted text-xs">Unsupported field type</span>
    }
}
