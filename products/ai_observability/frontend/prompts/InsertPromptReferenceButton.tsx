import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from 'lib/ui/quill'

import { insertPromptReferenceLogic } from './insertPromptReferenceLogic'
import { buildPromptReferenceTag } from './promptReferences'

interface ReferenceOption {
    tag: string
    promptName: string
    selectorLabel: string
}

export function InsertPromptReferenceButton({
    currentPromptName,
    onInsert,
}: {
    currentPromptName: string
    onInsert: (tag: string) => void
}): JSX.Element {
    const { promptOptions, promptOptionsLoading } = useValues(insertPromptReferenceLogic)
    const { loadPromptOptions } = useActions(insertPromptReferenceLogic)
    const [isOpen, setIsOpen] = useState(false)
    const [inputValue, setInputValue] = useState('')

    // Keyed by a human-readable string so the combobox's text filtering
    // matches what the item displays.
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
        optionsByKey.set(`${prompt.name} @ v${prompt.latest_version}`, {
            tag: buildPromptReferenceTag(prompt.name, { version: prompt.latest_version }),
            promptName: prompt.name,
            selectorLabel: `@ v${prompt.latest_version} (pinned)`,
        })
    }
    const items = [...optionsByKey.keys()]

    return (
        <>
            <LemonButton
                size="small"
                icon={<IconPlusSmall />}
                tooltip="Insert a reference to another prompt. Its content replaces the tag when the prompt is fetched."
                data-attr="llma-prompt-insert-reference-button"
                onClick={(e) => {
                    e.preventDefault()
                    setIsOpen(true)
                    setInputValue('')
                    loadPromptOptions()
                }}
            >
                Insert reference
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Insert prompt reference"
                description="Reference a label to pick up its future moves, or pin a version to freeze the content."
                width={480}
            >
                <Combobox
                    autoHighlight
                    items={items}
                    value={null}
                    onValueChange={(next: string | null) => {
                        const option = next ? optionsByKey.get(next) : undefined
                        if (option) {
                            onInsert(option.tag)
                            setIsOpen(false)
                        }
                    }}
                    inputValue={inputValue}
                    onInputValueChange={(value: string) => setInputValue(value)}
                    defaultOpen
                >
                    <ComboboxInput
                        placeholder="Search prompts"
                        autoFocus
                        showTrigger={false}
                        data-attr="llma-prompt-insert-reference-input"
                    />
                    <ComboboxContent>
                        <ComboboxEmpty>
                            {promptOptionsLoading ? 'Loading prompts...' : 'No matching prompts'}
                        </ComboboxEmpty>
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
            </LemonModal>
        </>
    )
}
