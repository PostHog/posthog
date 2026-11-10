import { useState } from 'react'

import { Input } from '@posthog/quill'

export interface QuillBehavioralNumberInputProps {
    value: number
    onChange: (value: number) => void
    'aria-label': string
    'data-attr'?: string
}

// The draft holds what is typed, so a cleared field stays empty until a whole number is entered,
// and leaving the field shows the saved value again.
export function QuillBehavioralNumberInput({
    value,
    onChange,
    'aria-label': ariaLabel,
    'data-attr': dataAttr,
}: QuillBehavioralNumberInputProps): JSX.Element {
    const [draft, setDraft] = useState<string | null>(null)

    return (
        <Input
            type="text"
            inputMode="numeric"
            size="sm"
            className="w-14"
            aria-label={ariaLabel}
            value={draft ?? String(value)}
            onChange={(event) => {
                const text = event.currentTarget.value
                setDraft(text)
                const next = Number(text)
                if (text.trim() !== '' && Number.isInteger(next) && next >= 1) {
                    onChange(next)
                }
            }}
            onBlur={() => setDraft(null)}
            onKeyDown={(event) => event.key === 'Enter' && setDraft(null)}
            data-attr={dataAttr}
        />
    )
}
