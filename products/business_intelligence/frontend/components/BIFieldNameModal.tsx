import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

export function BIFieldNameModal({
    name,
    onSave,
    onClose,
}: {
    name: string
    onSave: (name: string) => void
    onClose: () => void
}): JSX.Element {
    const [draft, setDraft] = useState(name)
    return (
        <LemonModal
            title="Rename field"
            isOpen
            onClose={onClose}
            footer={
                <LemonButton
                    type="primary"
                    disabledReason={!draft.trim() ? 'Enter a name' : undefined}
                    onClick={() => {
                        onSave(draft.trim())
                        onClose()
                    }}
                >
                    Save name
                </LemonButton>
            }
        >
            <LemonInput aria-label="Field name" value={draft} onChange={setDraft} autoFocus />
            <p className="mt-2 mb-0 text-secondary">
                This name applies to this field in this worksheet. The source field stays the same.
            </p>
        </LemonModal>
    )
}
