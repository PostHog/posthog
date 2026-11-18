import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { AccountCustomPropertyValue } from './accountPropertyTypes'

const NUMERIC_DISPLAY_TYPES = new Set(['number', 'currency', 'percent'])

// Percent values are stored as fractions and scaled by 100 for the input, which leaves binary
// artifacts: 0.29 * 100 is 28.999999999999996, so the field disagrees with the row's 29%. Scaling
// back on save needs the same treatment, because a stored 0.007 displays as 0.7 and divides to
// 0.006999999999999999. 15 significant digits clear the artifact and, unlike a fixed number of
// decimal places, keep very small fractions intact.
const clearFloatArtifacts = (value: number): number => Number(value.toPrecision(15))

const isHttpUrl = (value: string): boolean => {
    try {
        const { protocol } = new URL(value)
        return protocol === 'http:' || protocol === 'https:'
    } catch {
        return false
    }
}

// The server coerces each value to its display type and rejects a mismatch, so Save applies the
// same rules first. The checks stay no stricter than the server's, because a client that refuses a
// value the API would accept is worse than one that lets a rare rejection through.
const saveErrorFor = (draft: string | boolean, definition: CustomPropertyDefinitionApi): string | undefined => {
    if (typeof draft === 'boolean') {
        return undefined
    }
    if (NUMERIC_DISPLAY_TYPES.has(definition.display_type)) {
        return draft !== '' && Number.isFinite(Number(draft)) ? undefined : 'Enter a number to save'
    }
    if (definition.display_type === 'link') {
        return isHttpUrl(draft) ? undefined : 'Enter a valid HTTP or HTTPS URL'
    }
    if (definition.display_type === 'select') {
        return (definition.options ?? []).some((option) => option.label === draft) ? undefined : 'Pick an option'
    }
    // Saving a blank string stores an active row that every UI surface reads as "Not set", while
    // is_set filters and workflow audiences still match the account. Clearing is the only way to
    // unset a property, because it soft-deletes the row instead of writing a blank one.
    return draft === '' ? 'Enter a value, or use Clear value to unset it' : undefined
}

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
        definition.display_type === 'boolean'
            ? value === true || String(value) === 'true'
            : definition.display_type === 'percent' && value !== null && value !== ''
              ? String(clearFloatArtifacts(Number(value) * 100))
              : String(value ?? '')
    )
    const isDate = definition.display_type === 'date' || definition.display_type === 'datetime'
    const isNumeric = NUMERIC_DISPLAY_TYPES.has(definition.display_type)
    const numericDraft = typeof draft === 'string' && draft !== '' ? Number(draft) : undefined
    const saveError = saveErrorFor(draft, definition)

    const save = (): void => {
        if (saving || saveError) {
            return
        }
        if (typeof draft === 'boolean') {
            onSave(draft)
        } else if (isNumeric && numericDraft !== undefined && Number.isFinite(numericDraft)) {
            onSave(definition.display_type === 'percent' ? clearFloatArtifacts(numericDraft / 100) : numericDraft)
        } else if (!isNumeric) {
            onSave(draft)
        }
    }

    const confirmClear = (): void => {
        if (saving) {
            return
        }
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
                value={typeof draft === 'string' && draft ? dayjs(isDatetime ? draft : draft.slice(0, 10)) : null}
                onChange={(next) => {
                    if (next) {
                        const nextValue = isDatetime ? next.toISOString() : next.format('YYYY-MM-DD')
                        setDraft(nextValue)
                        onSave(nextValue)
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
                    disabled={saving}
                    checked={draft === true}
                    onChange={setDraft}
                    size="small"
                    label={draft === true ? 'Yes' : 'No'}
                    data-attr="account-property-value-input"
                />
            ) : definition.display_type === 'select' ? (
                <LemonSelect
                    disabledReason={saving ? 'Saving' : undefined}
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
                    suffix={definition.display_type === 'percent' ? <span>%</span> : undefined}
                    value={numericDraft}
                    onChange={(next) => setDraft(next === undefined ? '' : String(next))}
                    onPressEnter={save}
                    disabled={saving}
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
                    disabled={saving}
                    status={definition.display_type === 'link' && draft !== '' && saveError ? 'danger' : 'default'}
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
                    disabledReason={saving ? 'Saving' : value === null ? 'This property has no value' : undefined}
                    data-attr="account-property-clear"
                >
                    Clear value
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={onCancel}
                    disabledReason={saving ? 'Saving' : undefined}
                    data-attr="account-property-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={save}
                    loading={saving}
                    disabledReason={saveError}
                    data-attr="account-property-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
