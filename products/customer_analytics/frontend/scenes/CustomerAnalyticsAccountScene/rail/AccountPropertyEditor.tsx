import { useState } from 'react'

import { LemonButton, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { CustomPropertyValue } from '../accountDetailPropertiesLogic'

interface AccountPropertyEditorProps {
    definition: CustomPropertyDefinitionApi
    value: CustomPropertyValue | undefined
    saving: boolean
    onSave: (value: CustomPropertyValue) => void
    onCancel: () => void
}

const NUMERIC_TYPES = new Set(['number', 'currency', 'percent'])

// The draft mirrors the list's inline editor: booleans stay booleans, everything else is a
// string until save, when numeric types become numbers.
export function AccountPropertyEditor({
    definition,
    value,
    saving,
    onSave,
    onCancel,
}: AccountPropertyEditorProps): JSX.Element {
    const [draft, setDraft] = useState<string | boolean>(
        definition.display_type === 'boolean' ? value === true || String(value) === 'true' : (value ?? '').toString()
    )

    const save = (next: string | boolean = draft): void => {
        if (typeof next === 'boolean') {
            onSave(next)
            return
        }
        if (NUMERIC_TYPES.has(definition.display_type)) {
            const numeric = Number(next)
            if (next === '' || !Number.isFinite(numeric)) {
                return
            }
            onSave(numeric)
            return
        }
        onSave(next)
    }

    let input: JSX.Element
    if (definition.display_type === 'boolean') {
        input = <LemonSwitch checked={draft === true} onChange={setDraft} size="small" aria-label={definition.name} />
    } else if (definition.display_type === 'select') {
        input = (
            <LemonSelect
                value={typeof draft === 'string' ? draft : ''}
                onChange={(next) => setDraft(next ?? '')}
                options={(definition.options ?? []).map((option) => ({ value: option.label, label: option.label }))}
                size="small"
                fullWidth
            />
        )
    } else if (definition.display_type === 'date' || definition.display_type === 'datetime') {
        const isDatetime = definition.display_type === 'datetime'
        input = (
            <LemonCalendarSelectInput
                value={typeof draft === 'string' && draft ? dayjs(draft) : null}
                onChange={(next) => next && save(isDatetime ? next.toISOString() : next.format('YYYY-MM-DD'))}
                granularity={isDatetime ? 'minute' : 'day'}
                format={isDatetime ? 'MMM D, YYYY HH:mm' : 'MMM D, YYYY'}
                use24HourFormat
                onClickOutside={onCancel}
                onClose={onCancel}
                buttonProps={{ size: 'small', fullWidth: true }}
            />
        )
    } else if (NUMERIC_TYPES.has(definition.display_type)) {
        input = (
            <LemonInput
                type="number"
                value={typeof draft === 'string' && draft ? Number(draft) : undefined}
                onChange={(next) => setDraft(next === undefined ? '' : String(next))}
                onPressEnter={() => save()}
                size="small"
                step="any"
                fullWidth
                autoFocus
            />
        )
    } else {
        input = (
            <LemonInput
                type={definition.display_type === 'link' ? 'url' : 'text'}
                value={typeof draft === 'string' ? draft : ''}
                onChange={setDraft}
                onPressEnter={() => save()}
                size="small"
                fullWidth
                autoFocus
            />
        )
    }

    return (
        <div className="flex flex-col gap-1.5">
            {input}
            <div className="flex items-center gap-1">
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={() => save()}
                    loading={saving}
                    disabledReason={saving ? 'Saving…' : undefined}
                    data-attr="account-property-save"
                >
                    Save
                </LemonButton>
                <LemonButton size="xsmall" onClick={onCancel} data-attr="account-property-cancel">
                    Cancel
                </LemonButton>
            </div>
        </div>
    )
}
