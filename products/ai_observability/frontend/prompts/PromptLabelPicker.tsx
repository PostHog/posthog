import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import { llmPromptLogic } from './llmPromptLogic'
import { validatePromptLabelName } from './utils'

const CREATE_SENTINEL_PREFIX = '__create__:'

export function PromptLabelPicker({ version }: { version: number }): JSX.Element {
    const { promptLabels } = useValues(llmPromptLogic)
    const { requestSetLabel, closeLabelPicker } = useActions(llmPromptLogic)
    const [inputValue, setInputValue] = useState('')

    const trimmed = inputValue.trim()
    const existingNames = promptLabels.map((label) => label.name)
    const validationError = trimmed ? validatePromptLabelName(trimmed) : undefined

    const items: string[] = [...existingNames]
    if (existingNames.length === 0 && !trimmed) {
        items.push('production')
    }
    const createSentinel = `${CREATE_SENTINEL_PREFIX}${trimmed}`
    const showCreateItem = trimmed.length > 0 && !existingNames.includes(trimmed) && !validationError
    if (showCreateItem) {
        items.push(createSentinel)
    }

    const labelHint = (name: string): string | null => {
        const label = promptLabels.find((l) => l.name === name)
        if (!label) {
            return null
        }
        return label.version === version ? 'already on this version' : `currently on v${label.version}`
    }

    return (
        <Combobox
            autoHighlight
            items={items}
            value={null}
            onValueChange={(next: string | null) => {
                if (!next) {
                    return
                }
                const name = next.startsWith(CREATE_SENTINEL_PREFIX) ? next.slice(CREATE_SENTINEL_PREFIX.length) : next
                requestSetLabel(name, version)
            }}
            inputValue={inputValue}
            onInputValueChange={(value: string) => setInputValue(value)}
            defaultOpen
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeLabelPicker()
                }
            }}
        >
            <ComboboxInput
                placeholder="Label name"
                autoFocus
                showTrigger={false}
                data-attr="llma-prompt-label-picker-input"
            />
            <ComboboxContent>
                <ComboboxEmpty>{validationError ?? 'No matching labels'}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => {
                        if (item === createSentinel) {
                            return (
                                <ComboboxItem key={item} value={item}>
                                    Create label "{trimmed}"
                                </ComboboxItem>
                            )
                        }
                        const hint = labelHint(item)
                        return (
                            <ComboboxItem key={item} value={item}>
                                <span>{item}</span>
                                {hint ? <span className="text-xs text-secondary">{hint}</span> : null}
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
