import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import {
    ACCOUNT_ID_FIELDS,
    ACCOUNT_LIST_FIELDS,
    AccountNativePropertyKey,
    AccountNativePropertyValue,
} from '../accountNativeProperties'

export interface AccountNativePropertyFieldProps {
    propertyKey: AccountNativePropertyKey
    value: AccountNativePropertyValue
    draft: AccountNativePropertyValue
    editing: boolean
    saving: boolean
    disabledReason?: string
    onEdit: () => void
    onChange: (value: AccountNativePropertyValue) => void
    onSave: () => void
    onCancel: () => void
}

export function AccountNativePropertyField({
    propertyKey,
    value,
    draft,
    editing,
    saving,
    disabledReason,
    onEdit,
    onChange,
    onSave,
    onCancel,
}: AccountNativePropertyFieldProps): JSX.Element {
    const field = [...ACCOUNT_ID_FIELDS, ...ACCOUNT_LIST_FIELDS].find(({ key }) => key === propertyKey)!
    return (
        <div
            className="flex flex-col gap-1 min-w-0"
            role="group"
            aria-label={field.label}
            data-attr="account-native-property-row"
        >
            <div className="flex items-center gap-2 min-w-0 min-h-7">
                <span className="min-w-0 text-xs text-secondary truncate">{field.label}</span>
                {!editing ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconPencil />}
                        aria-label={`Edit ${field.label}`}
                        tooltip="Edit value"
                        disabledReason={disabledReason}
                        onClick={onEdit}
                        className="shrink-0"
                        data-attr="account-native-property-edit"
                    />
                ) : null}
            </div>
            {editing ? (
                <div className="flex flex-col gap-2 min-w-0">
                    {Array.isArray(draft) ? (
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            disableFiltering
                            value={draft}
                            onChange={onChange}
                            placeholder={field.placeholder}
                            fullWidth
                            disabledReason={saving ? 'Saving' : disabledReason}
                            data-attr="account-native-property-input"
                        />
                    ) : (
                        <LemonInput
                            aria-label={field.label}
                            value={draft}
                            onChange={onChange}
                            onPressEnter={saving ? undefined : onSave}
                            placeholder={field.placeholder}
                            fullWidth
                            disabled={saving || !!disabledReason}
                            autoFocus
                            data-attr="account-native-property-input"
                        />
                    )}
                    <div className="flex flex-wrap justify-end gap-1">
                        <LemonButton
                            size="xsmall"
                            onClick={onCancel}
                            disabledReason={saving ? 'Saving' : undefined}
                            data-attr="account-native-property-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            onClick={onSave}
                            loading={saving}
                            disabledReason={disabledReason}
                            data-attr="account-native-property-save"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <span className="text-sm break-words whitespace-pre-wrap" translate="no">
                    {Array.isArray(value) ? value.join(', ') || 'Not set' : value || 'Not set'}
                </span>
            )}
        </div>
    )
}
