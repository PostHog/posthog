import { ChangeEvent, KeyboardEvent, useEffect, useState } from 'react'

import { Textarea } from '@posthog/quill'

/** A multi-line text field that changes the source on blur or Cmd+Enter. */
export function DraftTextarea({
    value,
    onCommit,
    ariaLabel,
    rows = 6,
    placeholder,
}: {
    value: string
    onCommit: (value: string) => void
    ariaLabel: string
    rows?: number
    placeholder?: string
}): JSX.Element {
    const [draft, setDraft] = useState(value)
    useEffect(() => setDraft(value), [value])
    const commit = (): void => {
        if (draft !== value) {
            onCommit(draft)
        }
    }
    return (
        <Textarea
            value={draft}
            rows={rows}
            placeholder={placeholder}
            aria-label={ariaLabel}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                    commit()
                }
            }}
        />
    )
}
