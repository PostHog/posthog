import { ChangeEvent, KeyboardEvent, useEffect, useState } from 'react'

import { Input } from '@posthog/quill'

/** A text input that changes the source only on blur or Enter, so typing does not publish a version per key. */
export function DraftInput({
    value,
    onCommit,
    placeholder,
    ariaLabel,
}: {
    value: string
    onCommit: (value: string) => void
    placeholder?: string
    ariaLabel: string
}): JSX.Element {
    const [draft, setDraft] = useState(value)
    useEffect(() => setDraft(value), [value])
    const commit = (): void => {
        if (draft !== value) {
            onCommit(draft)
        }
    }
    return (
        <Input
            value={draft}
            placeholder={placeholder}
            aria-label={ariaLabel}
            onChange={(event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                if (event.key === 'Enter') {
                    commit()
                }
            }}
        />
    )
}
