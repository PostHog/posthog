import { useEffect, useId, useState } from 'react'

import { Textarea } from '@posthog/quill'

import { SceneSettingsRow } from './SceneSettingsRow'

export interface SceneDescriptionRowProps {
    value: string | null | undefined
    /** Called on blur when the text changed. Leave it out to show the description read-only. */
    onSave?: (value: string) => void
    disabledReason?: string | null
    label?: string
    placeholder?: string
    maxLength?: number
    dataAttr?: string
}

export function SceneDescriptionRow({
    value,
    onSave,
    disabledReason,
    label = 'Description',
    placeholder = 'Add a description',
    maxLength,
    dataAttr,
}: SceneDescriptionRowProps): JSX.Element {
    const id = useId()
    const [draft, setDraft] = useState(value ?? '')

    // A save elsewhere (another tab, the edit form) replaces what the field shows.
    useEffect(() => setDraft(value ?? ''), [value])

    return (
        <SceneSettingsRow label={label} htmlFor={id}>
            <Textarea
                id={id}
                className="w-full"
                rows={2}
                value={draft}
                placeholder={placeholder}
                maxLength={maxLength}
                readOnly={!onSave}
                disabledReason={disabledReason ?? undefined}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                    if (onSave && draft !== (value ?? '')) {
                        onSave(draft)
                    }
                }}
                data-attr={dataAttr}
            />
        </SceneSettingsRow>
    )
}
