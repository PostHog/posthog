import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { getNotebookWidgetDefinition } from '../notebookWidgetCatalog'
import { MarkdownNotebookEntityPicker } from './MarkdownNotebookEntityPicker'

type MarkdownNotebookNodeAttributeInputProps = {
    attributeKey: string
    autoFocus: boolean
    label: string
    tagName: string
    value: string
    onEntitySelect: (value: string | number) => void
    onTextChange: (value: string) => void
}

export function MarkdownNotebookNodeAttributeInput({
    attributeKey,
    autoFocus,
    label,
    tagName,
    value,
    onEntitySelect,
    onTextChange,
}: MarkdownNotebookNodeAttributeInputProps): JSX.Element {
    const [isPickerOpen, setIsPickerOpen] = useState(false)
    const widgetDefinition = getNotebookWidgetDefinition(tagName)
    const picker = widgetDefinition?.idProp === attributeKey ? widgetDefinition.picker : null

    return (
        <>
            <LemonInput
                aria-label={label}
                value={value}
                onChange={onTextChange}
                placeholder={label}
                autoFocus={autoFocus}
                suffix={
                    picker ? (
                        <LemonButton
                            type="tertiary"
                            size="small"
                            aria-label={`Select ${label.toLowerCase()}`}
                            onClick={() => setIsPickerOpen(true)}
                        >
                            Select
                        </LemonButton>
                    ) : null
                }
            />
            <MarkdownNotebookEntityPicker
                action="select"
                kind={isPickerOpen ? picker : null}
                onClose={() => setIsPickerOpen(false)}
                onSelect={(selection) => {
                    const selectedValue = selection.props[attributeKey]
                    if (typeof selectedValue === 'string' || typeof selectedValue === 'number') {
                        onEntitySelect(selectedValue)
                    }
                    setIsPickerOpen(false)
                }}
            />
        </>
    )
}
