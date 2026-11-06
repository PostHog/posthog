import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import { insertPromptReferenceLogic } from './insertPromptReferenceLogic'
import { buildPromptReferenceTag } from './promptReferences'

interface ReferenceOption {
    tag: string
    promptName: string
    selectorLabel: string
}

export function PromptReferencePicker({
    currentPromptName,
    onSelect,
}: {
    currentPromptName: string
    onSelect: (tag: string) => void
}): JSX.Element {
    const { promptOptions, promptOptionsLoading } = useValues(insertPromptReferenceLogic)
    const { loadPromptOptions } = useActions(insertPromptReferenceLogic)
    const [inputValue, setInputValue] = useState('')

    // Keys double as display strings so the combobox's text filtering matches
    // what the item shows. The "(pinned)" suffix cannot collide with a label
    // row: label names allow no spaces or parentheses.
    const optionsByKey = new Map<string, ReferenceOption>()
    for (const prompt of promptOptions) {
        if (prompt.name === currentPromptName) {
            continue
        }
        for (const label of prompt.all_labels) {
            optionsByKey.set(`${prompt.name} @ ${label.name}`, {
                tag: buildPromptReferenceTag(prompt.name, { label: label.name }),
                promptName: prompt.name,
                selectorLabel: `@ ${label.name} (follows the label)`,
            })
        }
        optionsByKey.set(`${prompt.name} @ v${prompt.latest_version} (pinned)`, {
            tag: buildPromptReferenceTag(prompt.name, { version: prompt.latest_version }),
            promptName: prompt.name,
            selectorLabel: `@ v${prompt.latest_version} (pinned)`,
        })
    }
    const items = [...optionsByKey.keys()]

    return (
        <Combobox
            autoHighlight
            items={items}
            value={null}
            onValueChange={(next: string | null) => {
                const option = next ? optionsByKey.get(next) : undefined
                if (option) {
                    onSelect(option.tag)
                }
            }}
            inputValue={inputValue}
            onInputValueChange={(value: string) => {
                setInputValue(value)
                loadPromptOptions(value)
            }}
            defaultOpen
        >
            <ComboboxInput
                placeholder="Search prompts"
                autoFocus
                showTrigger={false}
                data-attr="llma-prompt-insert-reference-input"
            />
            <ComboboxContent>
                <ComboboxEmpty>{promptOptionsLoading ? 'Loading prompts...' : 'No matching prompts'}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) => {
                        const option = optionsByKey.get(item)
                        return (
                            <ComboboxItem key={item} value={item} className="ps-2">
                                <span className="font-medium">{option?.promptName}</span>
                                <span className="text-xs text-secondary">{option?.selectorLabel}</span>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
