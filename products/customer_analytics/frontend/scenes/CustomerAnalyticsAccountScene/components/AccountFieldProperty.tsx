import { useState } from 'react'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

export interface AccountFieldPropertyProps {
    label: string
    value: string | string[]
    placeholder: string
    editing: boolean
    saving: boolean
    editDisabledReason?: string
    onEdit: () => void
    onCancel: () => void
    onSave: (value: string | string[]) => void
}

export function AccountFieldProperty({
    label,
    value,
    placeholder,
    editing,
    saving,
    editDisabledReason,
    onEdit,
    onCancel,
    onSave,
}: AccountFieldPropertyProps): JSX.Element {
    const [draft, setDraft] = useState<string | string[]>(value)
    const isList = Array.isArray(value)
    const isEmpty = isList ? value.length === 0 : !value.trim()

    return (
        <div className="flex flex-col gap-1 min-w-0" data-attr="account-view-field-row">
            <div className="flex items-center gap-1 min-w-0 min-h-7">
                <span className="text-xs text-secondary truncate">{label}</span>
                {!editing ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconPencil />}
                        tooltip="Edit value"
                        aria-label={`Edit ${label}`}
                        onClick={() => {
                            setDraft(value)
                            onEdit()
                        }}
                        disabledReason={editDisabledReason}
                        className="ml-auto"
                        data-attr="account-view-field-edit"
                    />
                ) : null}
            </div>
            {editing ? (
                <div className="flex flex-col gap-2 w-full">
                    {Array.isArray(draft) ? (
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            disableFiltering
                            value={draft}
                            onChange={setDraft}
                            placeholder={placeholder}
                            disabled={saving}
                            data-attr="account-view-field-list-input"
                        />
                    ) : (
                        <LemonInput
                            size="small"
                            fullWidth
                            autoFocus
                            value={draft}
                            onChange={setDraft}
                            onPressEnter={() => !saving && onSave(draft)}
                            placeholder={placeholder}
                            disabled={saving}
                            data-attr="account-view-field-input"
                        />
                    )}
                    <div className="flex justify-end gap-1">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={onCancel}
                            disabledReason={saving ? 'Saving value' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            onClick={() => onSave(draft)}
                            loading={saving}
                            data-attr="account-view-field-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            ) : isEmpty ? (
                <span className="text-sm text-muted">Not set</span>
            ) : (
                <span className="text-sm font-medium break-words select-all">{isList ? value.join(', ') : value}</span>
            )}
        </div>
    )
}
