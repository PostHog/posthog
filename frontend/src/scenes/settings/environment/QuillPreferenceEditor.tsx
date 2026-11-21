import { useId } from 'react'

import {
    Button,
    Field,
    FieldLabel,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectSeparator,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import type { ComposerEffortOption } from 'products/posthog_ai/frontend/utils/composerModels'

import type { AIRunPreferenceDraft } from './taskAgentDefaultsLogic'

// Select items need a non-null value, so "inherit" and "default effort" get a sentinel that maps back to null.
const UNSET_VALUE = '__unset__'

export interface ModelOptionGroup {
    title: string
    options: { value: string; label: string; labelInMenu: JSX.Element }[]
    footer?: JSX.Element
}

function fromSelectValue(value: unknown): string | null {
    return value === UNSET_VALUE ? null : (value as string)
}

export function QuillPreferenceEditor({
    draft,
    dirty,
    saving,
    inheritLabel,
    modelOptions,
    effortOptions,
    editingDisabled,
    onModelChange,
    onEffortChange,
    onSave,
    onReset,
    canReset,
    restrictionReason,
}: {
    draft: AIRunPreferenceDraft
    dirty: boolean
    saving: boolean
    inheritLabel: string
    modelOptions: ModelOptionGroup[]
    effortOptions: ComposerEffortOption[]
    editingDisabled: string | undefined
    onModelChange: (model: string | null) => void
    onEffortChange: (reasoningEffort: string | null) => void
    onSave: () => void
    onReset?: () => void
    canReset?: boolean
    restrictionReason?: string | null
}): JSX.Element {
    const id = useId()

    const modelLabel = (value: string): string =>
        modelOptions.flatMap((group) => group.options).find((option) => option.value === value)?.label ?? value
    const effortLabel = (value: string): string =>
        effortOptions.find((option) => option.value === value)?.label ?? value
    const effortDisabledReason = editingDisabled ?? (draft.model ? undefined : 'Pick a model first')

    return (
        <div className="flex flex-wrap items-end gap-2">
            <Field className="min-w-60 w-auto">
                <FieldLabel htmlFor={`${id}-model`}>Model</FieldLabel>
                <Select
                    value={draft.model ?? UNSET_VALUE}
                    onValueChange={(value) => onModelChange(fromSelectValue(value))}
                >
                    <SelectTrigger
                        id={`${id}-model`}
                        className="w-full"
                        disabledReason={editingDisabled}
                        data-attr="task-agent-default-model"
                    >
                        <SelectValue>
                            {(value: string) => (value === UNSET_VALUE ? inheritLabel : modelLabel(value))}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value={UNSET_VALUE}>{inheritLabel}</SelectItem>
                        {modelOptions.map((group) => (
                            <SelectGroup key={group.title}>
                                <SelectSeparator />
                                <SelectGroupLabel>{group.title}</SelectGroupLabel>
                                {group.options.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.labelInMenu}
                                    </SelectItem>
                                ))}
                                {group.footer}
                            </SelectGroup>
                        ))}
                    </SelectContent>
                </Select>
            </Field>
            <Field className="min-w-48 w-auto">
                <FieldLabel htmlFor={`${id}-effort`}>Reasoning effort</FieldLabel>
                <Select
                    value={draft.reasoning_effort ?? UNSET_VALUE}
                    onValueChange={(value) => onEffortChange(fromSelectValue(value))}
                >
                    <SelectTrigger
                        id={`${id}-effort`}
                        className="w-full"
                        disabledReason={effortDisabledReason}
                        data-attr="task-agent-default-effort"
                    >
                        <SelectValue>
                            {(value: string) => (value === UNSET_VALUE ? 'Default effort' : effortLabel(value))}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value={UNSET_VALUE}>Default effort</SelectItem>
                        {effortOptions.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </Field>
            <Button
                variant="primary"
                onClick={onSave}
                loading={saving}
                disabledReason={restrictionReason ?? (dirty ? undefined : 'No changes to save')}
            >
                Save
            </Button>
            {onReset && (
                <Button
                    variant="outline"
                    onClick={onReset}
                    loading={saving}
                    disabledReason={canReset ? undefined : 'Already using the project default'}
                >
                    Reset to project default
                </Button>
            )}
        </div>
    )
}
