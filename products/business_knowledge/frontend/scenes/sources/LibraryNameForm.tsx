import { useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export function LibraryNameForm({
    initialName,
    saving,
    submitLabel,
    onCancel,
    onSubmit,
}: {
    initialName: string
    saving: boolean
    submitLabel: string
    onCancel: () => void
    onSubmit: (name: string) => void
}): JSX.Element {
    const [name, setName] = useState(initialName)
    return (
        <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
                event.preventDefault()
                if (!name.trim() || saving) {
                    return
                }
                onSubmit(name.trim())
            }}
        >
            <LemonInput value={name} onChange={setName} placeholder="Library name" autoFocus />
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={onCancel} disabledReason={saving ? 'Saving' : undefined}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={saving}
                    disabledReason={!name.trim() ? 'Enter a name' : undefined}
                >
                    {submitLabel}
                </LemonButton>
            </div>
        </form>
    )
}
