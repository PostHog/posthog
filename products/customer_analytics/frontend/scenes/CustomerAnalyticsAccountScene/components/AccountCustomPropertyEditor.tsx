import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { AccountCustomPropertyValue } from './accountPropertyTypes'

const NUMERIC_DISPLAY_TYPES = new Set(['number', 'currency', 'percent'])

export interface AccountCustomPropertyEditorProps {
    definition: CustomPropertyDefinitionApi
    value: AccountCustomPropertyValue
    saving?: boolean
    onSave: (value: AccountCustomPropertyValue) => void
    onCancel: () => void
}

export function AccountCustomPropertyEditor({
    definition,
    value,
    saving = false,
    onSave,
    onCancel,
}: AccountCustomPropertyEditorProps): JSX.Element {
    const [draft, setDraft] = useState<string | boolean>(
        definition.display_type === 'boolean' ? value === true || String(value) === 'true' : String(value ?? '')
    )
    const isDate = definition.display_type === 'date' || definition.display_type === 'datetime'
    const isNumeric = NUMERIC_DISPLAY_TYPES.has(definition.display_type)
    const numericDraft = typeof draft === 'string' && draft !== '' ? Number(draft) : undefined
    const canSave = !isNumeric || (numericDraft !== undefined && Number.isFinite(numericDraft))

    const save = (): void => {
        if (typeof draft === 'boolean') {
            onSave(draft)
        } else if (isNumeric && numericDraft !== undefined && Number.isFinite(numericDraft)) {
            onSave(numericDraft)
        } else if (!isNumeric) {
            onSave(draft)
        }
    }

    const confirmClear = (): void => {
        LemonDialog.open({
            title: `Clear ${definition.name}?`,
            content: 'This will remove the current value. You can set it again later.',
            primaryButton: {
                children: 'Clear value',
                status: 'danger',
                onClick: () => onSave(null),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    if (isDate) {
        const isDatetime = definition.display_type === 'datetime'
        return (
            <LemonCalendarSelectInput
                value={typeof draft === 'string' && draft ? dayjs(draft) : null}
                onChange={(next) => {
                    if (next) {
                        onSave(isDatetime ? next.toISOString() : next.format('YYYY-MM-DD'))
                    } else {
                        confirmClear()
                    }
                }}
                granularity={isDatetime ? 'minute' : 'day'}
                format={isDatetime ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY'}
                use24HourFormat
                clearable
                onClickOutside={onCancel}
                onClose={onCancel}
                buttonProps={{
                    size: 'small',
                    fullWidth: true,
                    loading: saving,
                    'data-attr': 'account-property-date-input',
                }}
            />
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            {definition.display_type === 'boolean' ? (
                <LemonSwitch
                    checked={draft === true}
                    onChange={setDraft}
                    size="small"
                    label={draft === true ? 'Yes' : 'No'}
                    data-attr="account-property-value-input"
                />
            ) : definition.display_type === 'select' ? (
                <LemonSelect
                    value={typeof draft === 'string' ? draft : ''}
                    onChange={(next) => setDraft(next ?? '')}
                    options={(definition.options ?? []).map((option) => ({ value: option.label, label: option.label }))}
                    size="small"
                    fullWidth
                    data-attr="account-property-value-input"
                />
            ) : isNumeric ? (
                <LemonInput
                    type="number"
                    value={numericDraft}
                    onChange={(next) => setDraft(next === undefined ? '' : String(next))}
                    onPressEnter={save}
                    size="small"
                    step="any"
                    fullWidth
                    autoFocus
                    data-attr="account-property-value-input"
                />
            ) : (
                <LemonInput
                    type={definition.display_type === 'link' ? 'url' : 'text'}
                    value={typeof draft === 'string' ? draft : ''}
                    onChange={setDraft}
                    onPressEnter={save}
                    size="small"
                    fullWidth
                    autoFocus
                    data-attr="account-property-value-input"
                />
            )}
            <div className="flex flex-wrap items-center justify-end gap-1 w-full">
                <LemonButton
                    size="xsmall"
                    status="danger"
                    onClick={confirmClear}
                    disabledReason={value === null ? 'This property has no value' : undefined}
                    data-attr="account-property-clear"
                >
                    Clear value
                </LemonButton>
                <LemonButton size="xsmall" onClick={onCancel} data-attr="account-property-cancel">
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={save}
                    loading={saving}
                    disabledReason={!canSave ? 'Enter a number to save' : undefined}
                    data-attr="account-property-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
