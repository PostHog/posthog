import { useState } from 'react'

import { Input } from '@posthog/quill'

import { NumberVariable } from '~/queries/nodes/DataVisualization/types'

export interface QuillNumberVariableInputProps {
    id?: string
    variable: NumberVariable
    updateVariable: (variable: NumberVariable) => void
}

/** Number default input that, like `LemonInput`, keeps an empty or partial draft instead of forcing 0 mid-edit. */
export function QuillNumberVariableInput({ id, variable, updateVariable }: QuillNumberVariableInputProps): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)

    return (
        <Input
            id={id}
            type="number"
            placeholder="Default value"
            value={draft ?? variable.default_value}
            onChange={(event) => {
                const raw = event.target.value
                setDraft(raw)
                if (raw !== '' && !Number.isNaN(Number(raw))) {
                    updateVariable({ ...variable, default_value: Number(raw) })
                }
            }}
            onBlur={() => setDraft(null)}
        />
    )
}
