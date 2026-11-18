import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

export const InlineCreateForm = ({
    label,
    placeholder,
    loading,
    onSubmit,
    onCancel,
}: {
    label: string
    placeholder: string
    loading: boolean
    onSubmit: (name: string) => void
    onCancel?: () => void
}): JSX.Element => {
    const [name, setName] = useState('')

    return (
        <div className="flex flex-col gap-2 p-3 border border-border rounded bg-bg-light">
            <LemonLabel>{label}</LemonLabel>
            <div className="flex gap-2">
                <LemonInput
                    autoFocus
                    fullWidth
                    placeholder={placeholder}
                    maxLength={64}
                    value={name}
                    onChange={setName}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && name.trim()) {
                            onSubmit(name.trim())
                        }
                        if (e.key === 'Escape') {
                            onCancel?.()
                        }
                    }}
                    disabled={loading}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    loading={loading}
                    disabledReason={!name.trim() ? 'Enter a name' : undefined}
                    onClick={() => onSubmit(name.trim())}
                >
                    Create
                </LemonButton>
                {onCancel && (
                    <LemonButton type="secondary" size="small" onClick={onCancel} disabled={loading}>
                        Cancel
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
