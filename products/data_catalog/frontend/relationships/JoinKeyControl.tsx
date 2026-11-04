import { useMemo, useRef } from 'react'

import {
    Badge,
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import type { DatabaseSchemaTable } from '~/queries/schema/schema-general'

import type { JoinKeyMode, KeySelectOption } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

import { JoinSqlExpressionPopover } from './JoinSqlExpressionPopover'

const SELECT_TABLE_FIRST = 'Select a table first'

const KEY_MODE_LABELS: Record<JoinKeyMode, string> = {
    column: 'Column',
    sql_expression: 'SQL',
}

const KEY_MODES: JoinKeyMode[] = ['column', 'sql_expression']

interface JoinKeyControlProps {
    label: string
    mode: JoinKeyMode
    onModeChange: (mode: JoinKeyMode) => void
    columnOptions: KeySelectOption[]
    table: DatabaseSchemaTable | undefined
    tableName: string | null
    value: string | null
    onSelectColumn: (column: string) => void
    onExpressionChange: (expression: string) => void
    sqlPlaceholder: string
}

function ColumnCombobox({
    label,
    columnOptions,
    table,
    tableName,
    value,
    onSelectColumn,
}: Omit<JoinKeyControlProps, 'mode' | 'onModeChange' | 'sqlPlaceholder' | 'onExpressionChange'>): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const disabledReasons = new Map(columnOptions.map((option) => [option.value, option.disabledReason]))
    const typeByColumn = useMemo(
        () => new Map(Object.values(table?.fields ?? {}).map((field) => [field.name, field.type])),
        [table]
    )

    return (
        <Combobox
            items={columnOptions.map((option) => option.value)}
            value={value}
            onValueChange={(next: string | null) => next && onSelectColumn(next)}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        className="h-8 max-w-60"
                        aria-label={label}
                        disabledReason={tableName ? undefined : SELECT_TABLE_FIRST}
                    />
                }
            >
                <span className="min-w-0 truncate">{value || 'Select a key'}</span>
            </ComboboxTrigger>
            <ComboboxContent anchor={triggerRef} align="start" className="min-w-70">
                <ComboboxInput placeholder="Search columns..." aria-label="Search columns" showTrigger={false} />
                <ComboboxEmpty>No columns match that search.</ComboboxEmpty>
                <ComboboxList>
                    {(columnName: string) => {
                        const disabledReason = disabledReasons.get(columnName)
                        const type = typeByColumn.get(columnName)
                        return (
                            <ComboboxItem key={columnName} value={columnName} disabled={!!disabledReason}>
                                <div className="flex min-w-0 flex-col">
                                    <span className="flex items-center gap-2">
                                        <span className="truncate">{columnName}</span>
                                        {type && <Badge variant="success">{type}</Badge>}
                                    </span>
                                    {disabledReason && (
                                        <Text size="xs" variant="muted">
                                            {disabledReason}
                                        </Text>
                                    )}
                                </div>
                            </ComboboxItem>
                        )
                    }}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

export function JoinKeyControl(props: JoinKeyControlProps): JSX.Element {
    const { label, mode, onModeChange, tableName, value, onExpressionChange, sqlPlaceholder } = props

    return (
        <div className="flex items-center gap-1">
            {mode === 'column' ? (
                <ColumnCombobox {...props} />
            ) : (
                <JoinSqlExpressionPopover
                    value={value ?? ''}
                    tableName={tableName ?? ''}
                    placeholder={sqlPlaceholder}
                    onChange={onExpressionChange}
                    disabledReason={tableName ? undefined : SELECT_TABLE_FIRST}
                    ariaLabel={label}
                />
            )}
            <ToggleGroup
                variant="default"
                aria-label={`${label} type`}
                value={[mode]}
                onValueChange={(next: string[]) => next[0] && onModeChange(next[0] as JoinKeyMode)}
            >
                {KEY_MODES.map((keyMode) => (
                    <ToggleGroupItem
                        key={keyMode}
                        value={keyMode}
                        disabledReason={tableName ? undefined : SELECT_TABLE_FIRST}
                    >
                        {KEY_MODE_LABELS[keyMode]}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
