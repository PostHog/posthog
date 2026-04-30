/**
 * Data warehouse config form. The table picker itself is reused via
 * `<MenuFilterCombobox drillTo={DataWarehouse}>` — this file only owns
 * the post-pick column-mapping form.
 */
import { useMemo, useState } from 'react'

import {
    Badge,
    Button,
    DialogFooter,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    ItemContent,
    ItemDescription,
    ItemTitle,
    ScrollArea,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { TaxonomicDefinitionTypes } from '../types'
import { MenuFilterHeader } from './Header'
import { CommitFn, MenuFilterEntry, TaxonomicFilterGroup } from './types'

interface DwhColumnOption {
    name: string
    type?: string
}

export interface MenuFilterDwhConfigProps {
    table: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    onCommit: CommitFn
    onBack: () => void
}

export function MenuFilterDwhConfig({ table, group, onCommit, onBack }: MenuFilterDwhConfigProps): JSX.Element {
    const tableName = group.getName?.(table) ?? (table as { name?: string }).name ?? 'table'
    const columns: DwhColumnOption[] = useMemo(() => {
        const fields = (table as { fields?: Record<string, { type?: string }> }).fields ?? {}
        return Object.entries(fields).map(([name, field]) => ({ name, type: field?.type }))
    }, [table])

    const guess = (predicate: (col: string) => boolean): DwhColumnOption | null =>
        columns.find((c) => predicate(c.name)) ?? columns[0] ?? null

    // Prefer the previously-saved column mapping when the form is
    // re-opened from an existing selection — `handleCommit` merges the
    // form values into `item`, so they roundtrip back here as
    // `id_field` / `timestamp_field` / `distinct_id_field`.
    const preset = (key: string): DwhColumnOption | null => {
        const v = (table as unknown as Record<string, unknown>)[key]
        return typeof v === 'string' ? columns.find((c) => c.name === v) ?? null : null
    }

    const [idField, setIdField] = useState<DwhColumnOption | null>(
        () => preset('id_field') ?? guess((c) => c === 'id' || c.endsWith('_id'))
    )
    const [timestampField, setTimestampField] = useState<DwhColumnOption | null>(
        () =>
            preset('timestamp_field') ??
            guess((c) => c === 'timestamp' || c.includes('time') || c.includes('created') || c.includes('date'))
    )
    const [distinctIdField, setDistinctIdField] = useState<DwhColumnOption | null>(
        () => preset('distinct_id_field') ?? guess((c) => c.includes('distinct'))
    )

    const canSubmit = !!idField && !!timestampField && !!distinctIdField

    const entry: MenuFilterEntry = useMemo(
        () => ({
            item: table,
            group,
            name: tableName,
        }),
        [table, group, tableName]
    )

    return (
        <div
            className="flex flex-col flex-1 min-h-0"
            onKeyDown={(e) => {
                if (e.key === 'Escape') {
                    // stopPropagation so the popover's own dismiss
                    // doesn't fire `closeAll` — back should land on the
                    // menu.
                    e.preventDefault()
                    e.stopPropagation()
                    onBack()
                }
            }}
        >
            <MenuFilterHeader title="Configure data warehouse table" onBack={onBack} />
            <div className="flex flex-col flex-1 min-h-0">
                <ScrollArea className="flex-1 min-h-0">
                    <div className="flex flex-col gap-4 p-3">
                        <FieldDescription className="!mt-0">
                            Table: <Badge variant="info">{tableName}</Badge>
                        </FieldDescription>
                        <ColumnField label="ID Field" value={idField} onValueChange={setIdField} options={columns} />
                        <ColumnField
                            label="Timestamp Field"
                            value={timestampField}
                            onValueChange={setTimestampField}
                            options={columns}
                        />
                        <ColumnField
                            label="Distinct ID Field"
                            value={distinctIdField}
                            onValueChange={setDistinctIdField}
                            options={columns}
                        />
                    </div>
                </ScrollArea>
                <DialogFooter>
                    <Button variant="outline" onClick={onBack}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        disabled={!canSubmit}
                        onClick={() =>
                            onCommit(entry, {
                                id_field: idField?.name,
                                timestamp_field: timestampField?.name,
                                distinct_id_field: distinctIdField?.name,
                            })
                        }
                    >
                        Select
                    </Button>
                </DialogFooter>
            </div>
        </div>
    )
}

interface ColumnFieldProps {
    label: string
    value: DwhColumnOption | null
    onValueChange: (value: DwhColumnOption | null) => void
    options: DwhColumnOption[]
}

function ColumnField({ label, value, onValueChange, options }: ColumnFieldProps): JSX.Element {
    return (
        <Field>
            <FieldLabel>
                {label} <span className="text-destructive">*</span>
            </FieldLabel>
            <FieldContent>
                <Select<DwhColumnOption>
                    value={value ?? undefined}
                    onValueChange={(v) => onValueChange((v as DwhColumnOption | null) ?? null)}
                    itemToStringLabel={(o) => o.name}
                    itemToStringValue={(o) => o.name}
                >
                    <SelectTrigger render={(props) => <Button variant="outline" {...props} className="h-min" />}>
                        <SelectValue placeholder="Select column…">
                            {(option: DwhColumnOption | null) =>
                                option ? (
                                    <ItemContent variant="menuItem">
                                        <ItemTitle>{option.name}</ItemTitle>
                                        {option.type && (
                                            <ItemDescription className="leading-none">{option.type}</ItemDescription>
                                        )}
                                    </ItemContent>
                                ) : null
                            }
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent className="min-w-(--anchor-width)" align="end" sideOffset={8}>
                        <SelectGroup>
                            {options.map((o) => (
                                <SelectItem key={o.name} value={o} className="py-0">
                                    <ItemContent variant="menuItem">
                                        <ItemTitle>{o.name}</ItemTitle>
                                        {o.type && <ItemDescription className="leading-none">{o.type}</ItemDescription>}
                                    </ItemContent>
                                </SelectItem>
                            ))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </FieldContent>
        </Field>
    )
}
