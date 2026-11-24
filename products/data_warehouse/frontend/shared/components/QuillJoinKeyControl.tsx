import { Field as KeaField } from 'kea-forms'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { QuillHogQLDropdown } from 'lib/components/HogQLDropdown/QuillHogQLDropdown'

import { JoinKeyMode, KeySelectOption } from '../logics/viewLinkLogic'
import { QuillJoinKeyColumnCombobox } from './QuillJoinKeyColumnCombobox'

const KEY_MODE_OPTIONS: { value: JoinKeyMode; label: string }[] = [
    { value: 'column', label: 'Column' },
    { value: 'sql_expression', label: 'SQL' },
]

export interface QuillJoinKeyControlProps {
    formFieldName: 'source_table_key' | 'joining_table_key'
    mode: JoinKeyMode
    onModeChange: (mode: JoinKeyMode) => void
    columnOptions: KeySelectOption[]
    onSelectColumn: (key: string) => void
    tableName: string | null
    sqlPlaceholder: string
    'aria-label': string
}

export function QuillJoinKeyControl({
    formFieldName,
    mode,
    onModeChange,
    columnOptions,
    onSelectColumn,
    tableName,
    sqlPlaceholder,
    'aria-label': ariaLabel,
}: QuillJoinKeyControlProps): JSX.Element {
    const tableDisabledReason = tableName ? undefined : 'Select a table first'

    return (
        <div className="flex flex-wrap items-center gap-1">
            <KeaField name={formFieldName} noStyle>
                {({ value, onChange }) =>
                    mode === 'column' ? (
                        <QuillJoinKeyColumnCombobox
                            options={columnOptions}
                            value={value ?? null}
                            onChange={(key) => {
                                onChange(key)
                                onSelectColumn(key)
                            }}
                            disabledReason={tableDisabledReason}
                            aria-label={ariaLabel}
                        />
                    ) : (
                        <QuillHogQLDropdown
                            hogQLValue={value ?? ''}
                            onHogQLValueChange={onChange}
                            tableName={tableName ?? ''}
                            hogQLEditorPlaceholder={sqlPlaceholder}
                        />
                    )
                }
            </KeaField>
            <ToggleGroup
                variant="outline"
                aria-label={`${ariaLabel} type`}
                value={[mode]}
                onValueChange={(next: string[]) => {
                    if (next[0]) {
                        onModeChange(next[0] as JoinKeyMode)
                    }
                }}
            >
                {KEY_MODE_OPTIONS.map((option) => (
                    <ToggleGroupItem key={option.value} value={option.value} disabledReason={tableDisabledReason}>
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
