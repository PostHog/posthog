import { useEffect, useState } from 'react'

import { Field, Textarea } from '@posthog/quill'

const MAX_DESCRIPTION_LENGTH = 600

export function QuillConditionSetDescription({
    description,
    dataAttr,
    onSave,
}: {
    description: string
    dataAttr: string
    onSave: (description: string) => void
}): JSX.Element {
    const [draft, setDraft] = useState(description)

    // Discarding changes resets `description`, and a stale draft would be saved back on the next blur.
    useEffect(() => setDraft(description), [description])

    function handleBlur(): void {
        if (draft !== description) {
            onSave(draft)
        }
    }

    return (
        <Field className="max-w-md">
            <Textarea
                aria-label="Description"
                placeholder="Description (optional)"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={handleBlur}
                maxLength={MAX_DESCRIPTION_LENGTH}
                data-attr={dataAttr}
            />
        </Field>
    )
}
