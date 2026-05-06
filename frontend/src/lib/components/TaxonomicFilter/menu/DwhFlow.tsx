/**
 * Data warehouse config form, rendered as a Quill Dialog (modal) on top
 * of the popover so the form gets full breathing room instead of being
 * squeezed inside the 720px popover.
 *
 * Flow:
 *   - User picks a DWH table from the combobox (`drillTo='dwh-pick'`
 *     in `TaxonomicFilterMenu`).
 *   - Clicking a row transitions to `dwh-config` and opens this Dialog
 *     while the popover stays underneath at the table list.
 *   - "Cancel" (or X / overlay / Esc) calls `onBack` → state returns
 *     to `dwh-pick` so the user can pick a different table.
 *   - "Select" calls `onCommit` → `closeAll` which dismisses both the
 *     dialog and the parent popover.
 *
 * Mirrors the legacy `FunnelDataWarehouseStepDefinitionPopover` flow:
 *   - DatabaseTablePreview at the top so the user can sanity-check the
 *     data they're configuring against.
 *   - One tab per `dataWarehousePopoverFields` entry (Aggregation
 *     target / Timestamp / Unique ID by default).
 *   - Per-field description + a column dropdown filtered to the
 *     allowed Postgres types for that field.
 *   - HogQL fallback (lazy Monaco) when the active field has
 *     `allowHogQL: true` and the chosen value isn't a real column.
 *   - When `insightProps` is supplied, the aggregation-target tab
 *     reads `funnelDataLogic.querySource` to render the
 *     "Current aggregation target is set to person/group" message
 *     that mirrors the legacy popover.
 */
import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import {
    Badge,
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tabs,
    TabsList,
    TabsTrigger,
} from '@posthog/quill'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import type { TablePreviewExpressionColumn } from 'lib/components/TablePreview/types'
import { Link } from 'lib/lemon-ui/Link'
import { funnelDataLogic } from 'scenes/funnels/funnelDataLogic'
import { urls } from 'scenes/urls'

import type { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { defaultDataWarehousePopoverFields } from '../taxonomicFilterLogic'
import { DataWarehousePopoverField, TaxonomicDefinitionTypes } from '../types'
import { CommitFn, MenuFilterEntry, TaxonomicFilterGroup } from './types'

/** Allowed column types per field key — copied from the legacy logic so
 *  the dropdowns surface the same options as the funnel popover. */
const ALLOWED_COLUMN_TYPES_BY_FIELD_KEY: Record<string, DatabaseSerializedFieldType[]> = {
    aggregation_target_field: ['string'],
    timestamp_field: ['datetime', 'date', 'string'],
    id_field: ['string', 'integer', 'decimal', 'float'],
    distinct_id_field: ['string'],
}

/** Default descriptions per known field key — used when the consumer
 *  doesn't pass a `description` on the field. Keeps the form
 *  self-explanatory even when the caller hands us the bare default
 *  `defaultDataWarehousePopoverFields` array. Mirrors the legacy
 *  `EDITABLE_FIELD_EXPLANATIONS` table. */
const DEFAULT_FIELD_DESCRIPTIONS: Record<string, string> = {
    aggregation_target_field: 'Used to match people or groups across funnel steps.',
    timestamp_field: 'Used to order step timing and apply the funnel date range.',
    id_field: 'Used as the unique row ID to detect duplicate records.',
    distinct_id_field: 'Used to associate this row with a person via distinct_id.',
}

const HIDDEN_FIELD_TYPES: DatabaseSerializedFieldType[] = ['lazy_table', 'virtual_table', 'view', 'materialized_view']
const LINKED_TABLE_TYPES: DatabaseSerializedFieldType[] = ['lazy_table', 'virtual_table']

interface ColumnOption {
    name: string
    type: DatabaseSerializedFieldType
}

export interface MenuFilterDwhConfigProps {
    table: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    onCommit: CommitFn
    onBack: () => void
    /** Field keys + labels to expose as tabs. Defaults to the standard `id_field` / `timestamp_field` / `distinct_id_field` bundle. */
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    /** When supplied, the aggregation-target tab reads `funnelDataLogic` for context (group vs person, HogQL aggregation). */
    insightProps?: InsightLogicProps
}

export function MenuFilterDwhConfig({
    table,
    group,
    onCommit,
    onBack,
    dataWarehousePopoverFields = defaultDataWarehousePopoverFields,
    insightProps,
}: MenuFilterDwhConfigProps): JSX.Element {
    const tableName = group.getName?.(table) ?? (table as { name?: string }).name ?? 'table'

    // ---- columns ---------------------------------------------------------
    const columns: ColumnOption[] = useMemo(() => {
        const fields =
            (table as { fields?: Record<string, { name?: string; type?: DatabaseSerializedFieldType }> }).fields ?? {}
        return Object.values(fields)
            .filter((f) => !!f?.name && !!f?.type)
            .map((f) => ({ name: f.name as string, type: f.type as DatabaseSerializedFieldType }))
    }, [table])

    const linkedTables = useMemo(
        () => columns.filter((c) => LINKED_TABLE_TYPES.includes(c.type)).map((c) => c.name),
        [columns]
    )

    // ---- local definition (per-field current value) ---------------------
    type FieldValues = Record<string, string | undefined>
    const initialValues: FieldValues = useMemo(() => {
        const out: FieldValues = {}
        for (const f of dataWarehousePopoverFields) {
            const existing = (table as unknown as Record<string, unknown>)[f.key]
            if (typeof existing === 'string' && existing.length > 0) {
                out[f.key] = existing
                continue
            }
            // Cheap heuristic so the user lands on a likely-correct column
            // when the table hasn't been configured before.
            const guess =
                f.key === 'id_field'
                    ? columns.find((c) => c.name === 'id' || c.name.endsWith('_id'))
                    : f.key === 'timestamp_field'
                      ? columns.find(
                            (c) =>
                                c.name === 'timestamp' ||
                                c.name.includes('time') ||
                                c.name.includes('created') ||
                                c.name.includes('date')
                        )
                      : f.key === 'distinct_id_field'
                        ? columns.find((c) => c.name.includes('distinct'))
                        : columns[0]
            out[f.key] = guess?.name
        }
        return out
    }, [table, columns, dataWarehousePopoverFields])

    const [values, setValues] = useState<FieldValues>(initialValues)

    // ---- active tab -----------------------------------------------------
    const [activeFieldKey, setActiveFieldKey] = useState<string>(() => dataWarehousePopoverFields[0]?.key ?? 'id_field')
    const activeField = useMemo(
        () => dataWarehousePopoverFields.find((f) => f.key === activeFieldKey),
        [activeFieldKey, dataWarehousePopoverFields]
    )

    // ---- column options for the active field ---------------------------
    const activeFieldOptions = useMemo<ColumnOption[]>(() => {
        const allowed = ALLOWED_COLUMN_TYPES_BY_FIELD_KEY[activeFieldKey] ?? []
        const filtered = allowed.length > 0 ? columns.filter((c) => allowed.includes(c.type)) : columns
        return filtered
    }, [activeFieldKey, columns])

    const activeFieldValue = values[activeFieldKey] ?? ''
    // HogQL mode — true whenever the active value isn't a real column on the
    // table (including `''`, the sentinel for "user picked SQL expression
    // but hasn't typed anything yet"). Keeping the truthy guard off this
    // check is what surfaces the Monaco editor as soon as the user selects
    // `SQL expression` from the dropdown.
    const activeFieldIsHogQL = useMemo(
        () => !!activeField?.allowHogQL && !columns.some((c) => c.name === activeFieldValue),
        [activeField, activeFieldValue, columns]
    )

    // ---- preview -------------------------------------------------------
    const previewTable = useMemo(() => {
        const fields = (table as { fields?: Record<string, { type?: DatabaseSerializedFieldType }> }).fields ?? {}
        return {
            ...(table as object),
            fields: Object.fromEntries(
                Object.entries(fields).filter(
                    ([, f]) => !HIDDEN_FIELD_TYPES.includes(f?.type as DatabaseSerializedFieldType)
                )
            ),
        } as typeof table
    }, [table])

    const previewExpressionColumns: TablePreviewExpressionColumn[] = useMemo(() => {
        const tableFieldNames = new Set(columns.map((c) => c.name))
        const usedKeys = new Set(tableFieldNames)
        const out: TablePreviewExpressionColumn[] = []
        for (const f of dataWarehousePopoverFields) {
            const v = values[f.key]
            if (typeof v !== 'string') {
                continue
            }
            const expression = v.trim()
            if (!expression || tableFieldNames.has(expression)) {
                continue
            }
            const keyBase = `__${f.key}_hogql_expression`
            let key = keyBase
            let suffix = 2
            while (usedKeys.has(key)) {
                key = `${keyBase}_${suffix}`
                suffix += 1
            }
            usedKeys.add(key)
            out.push({ key, expression, label: `${f.label} (SQL expression)`, type: 'SQL expression' })
        }
        return out
    }, [columns, dataWarehousePopoverFields, values])

    const previewSelectedKey = useMemo(() => {
        const expr = previewExpressionColumns.find((c) => c.key.startsWith(`__${activeFieldKey}_hogql_expression`))
        return expr?.key ?? activeFieldValue
    }, [previewExpressionColumns, activeFieldKey, activeFieldValue])

    const canSubmit = useMemo(
        () =>
            dataWarehousePopoverFields.every((f) => {
                if (f.optional) {
                    return true
                }
                const v = values[f.key]
                return typeof v === 'string' && v.length > 0
            }),
        [dataWarehousePopoverFields, values]
    )

    const entry: MenuFilterEntry = useMemo(
        () => ({
            item: table,
            group,
            name: tableName,
        }),
        [table, group, tableName]
    )

    return (
        <Dialog
            open
            // Open is bound to render — when this component unmounts the
            // dialog disappears. `onOpenChange(false)` fires for X /
            // overlay / Esc; route those to `onBack` so the parent state
            // machine returns to `dwh-pick` (popover keeps showing the
            // table list).
            onOpenChange={(open) => {
                if (!open) {
                    onBack()
                }
            }}
        >
            <DialogContent
                // `nested` because a popover with focus management is
                // already open underneath; tells base-ui to stack focus
                // traps + handle overlay clicks correctly.
                nested
                // `quill-dialog--wide` is defined in
                // `frontend/src/styles/quill-bridge.scss` — it widens
                // the dialog to ~72rem so the LemonTable preview gets
                // horizontal breathing room. Vertical behaviour
                // (viewport-bounded `max-height`, three-row grid, body
                // scroll) is now baked into Quill itself.
                className="quill-dialog--wide gap-0 p-0"
            >
                <DialogHeader className="px-4 py-3 border-b">
                    <DialogTitle>Configure data warehouse table</DialogTitle>
                </DialogHeader>
                {/* `DialogBody` defaults to a `ScrollArea` (per Quill)
                    so we get scroll shadows and edge-overflow data
                    attrs for free. The viewport already gets
                    `padding-block: 1rem` from Quill's body styling, so
                    the inner stack just needs row gap + min-width
                    bound for the LemonTable. */}
                <DialogBody>
                    <div className="flex flex-col gap-4 min-w-0">
                        <FieldDescription className="!mt-0">
                            Table: <Badge variant="info">{tableName}</Badge>
                        </FieldDescription>

                        {/* `data-not-quill` resets the colour-token rebinds
                            that `[data-quill]` applies on the popover root,
                            so the legacy DatabaseTablePreview keeps its
                            PostHog colours instead of inheriting Quill's. */}
                        <div data-not-quill className="flex min-w-0 overflow-x-auto">
                            <DatabaseTablePreview
                                table={previewTable as never}
                                selectedKey={previewSelectedKey || undefined}
                                limit={25}
                                expressionColumns={previewExpressionColumns}
                                emptyMessage="No table selected"
                                bordered
                            />
                        </div>

                        <Tabs value={activeFieldKey} onValueChange={(v) => setActiveFieldKey(v)}>
                            <TabsList className="bg-muted">
                                {dataWarehousePopoverFields.map((f) => (
                                    <TabsTrigger key={f.key} value={f.key}>
                                        {f.label}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </Tabs>

                        {activeField && (
                            <ActiveFieldEditor
                                field={activeField}
                                value={activeFieldValue}
                                isHogQL={activeFieldIsHogQL}
                                options={activeFieldOptions}
                                tableName={tableName}
                                linkedTables={linkedTables}
                                onChange={(v) => setValues((prev) => ({ ...prev, [activeField.key]: v }))}
                                insightProps={insightProps}
                            />
                        )}
                    </div>
                </DialogBody>
                <DialogFooter className="px-4 py-3 border-t">
                    <Button variant="outline" onClick={onBack}>
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        disabled={!canSubmit}
                        onClick={() =>
                            // `handleCommit` upstream calls `closeAll`,
                            // which collapses the popover too — so Select
                            // dismisses both the dialog and the menu in
                            // one click.
                            onCommit(entry, {
                                ...values,
                            } as Record<string, unknown>)
                        }
                    >
                        Select
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

interface ActiveFieldEditorProps {
    field: DataWarehousePopoverField
    value: string
    isHogQL: boolean
    options: ColumnOption[]
    tableName: string
    linkedTables: string[]
    onChange: (v: string) => void
    insightProps?: InsightLogicProps
}

/**
 * Active-field editor: column dropdown + optional HogQL fallback. Split
 * out so it can mount the funnel logic conditionally (only when
 * `insightProps` is supplied) without that cost on every render.
 */
function ActiveFieldEditor({
    field,
    value,
    isHogQL,
    options,
    tableName,
    linkedTables,
    onChange,
    insightProps,
}: ActiveFieldEditorProps): JSX.Element {
    const description = field.description ?? DEFAULT_FIELD_DESCRIPTIONS[field.key]
    return (
        <Field>
            <FieldLabel className="text-sm font-semibold">{field.label}</FieldLabel>
            <FieldContent className="gap-3">
                {description && <FieldDescription className="!mt-0">{description}</FieldDescription>}

                {field.key === 'aggregation_target_field' && (
                    <AggregationTargetContext insightProps={insightProps} isHogQL={isHogQL} />
                )}

                <ColumnSelect options={options} value={value} onChange={onChange} allowHogQL={!!field.allowHogQL} />

                {field.allowHogQL && isHogQL && (
                    // Render the rich `HogQLEditor` inline (full width) —
                    // skipping the legacy `HogQLDropdown` button-trigger
                    // wrapper — so users see the editor + placeholder
                    // examples + "Update SQL expression" button + "Learn
                    // more about SQL" link without an extra click.
                    <HogQLEditor
                        value={value}
                        onChange={(v) => onChange(v)}
                        metadataSource={{
                            kind: NodeKind.HogQLQuery,
                            query: `SELECT * FROM ${field.tableName ?? tableName}`,
                        }}
                        placeholder={
                            linkedTables.length
                                ? `Enter an SQL Expression, for example:\n- json_column.my_person_id\n- person_distinct_ids.person_id\n\nYou can also reference these linked tables: ${linkedTables.join(', ')}`
                                : `Enter an SQL Expression, for example:\n- json_column.my_person_id\n- person_distinct_ids.person_id`
                        }
                        disableAutoFocus
                    />
                )}
            </FieldContent>
        </Field>
    )
}

interface AggregationTargetContextProps {
    /** Optional — when set, drives the "set to person/group/custom" copy. */
    insightProps?: InsightLogicProps
    isHogQL: boolean
}

function AggregationTargetContext({ insightProps, isHogQL }: AggregationTargetContextProps): JSX.Element {
    return (
        <FieldDescription className="!mt-0 flex flex-col gap-1">
            {insightProps ? (
                <FunnelAggregationDescription insightProps={insightProps} />
            ) : (
                <span>
                    Selected field needs to match the <b>Person ID</b> (or <b>Group ID</b> when aggregating by group).
                </span>
            )}
            <span>
                If this field is not directly available on the table, add it by joining in{' '}
                <Link to={urls.sqlEditor()} target="_blank" className="underline text-primary">
                    SQL editor
                </Link>{' '}
                using fields like <code>distinct_id</code> or <code>email</code>.{' '}
                <Link
                    to="https://posthog.com/docs/data-warehouse/join#table-joins"
                    target="_blank"
                    className="underline text-primary"
                >
                    For more help
                </Link>
                . {isHogQL ? '(currently using SQL expression)' : ''}
            </span>
        </FieldDescription>
    )
}

/**
 * Splits the funnel-context-aware copy into its own component so we only
 * mount `funnelDataLogic` when an `insightProps` is supplied. The
 * surrounding joining-hint paragraph still renders regardless.
 */
function FunnelAggregationDescription({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element {
    const { querySource } = useValues(funnelDataLogic(insightProps))
    const isAggregatingByGroup = querySource?.aggregation_group_type_index != null
    const isAggregatingByHogQL = !!querySource?.funnelsFilter?.funnelAggregateByHogQL && !isAggregatingByGroup
    if (isAggregatingByHogQL) {
        return (
            <span>
                Current aggregation target is custom. The selected field needs to match the custom aggregation value.
            </span>
        )
    }
    return (
        <span>
            Current aggregation target is set to <b>{isAggregatingByGroup ? 'group' : 'person'}</b>, so the selected
            field needs to match the <b>{isAggregatingByGroup ? 'Group ID' : 'Person ID'}</b>.
        </span>
    )
}

interface ColumnSelectProps {
    options: ColumnOption[]
    value: string
    onChange: (v: string) => void
    allowHogQL: boolean
}

const HOGQL_SENTINEL = '__hogql__'

function ColumnSelect({ options, value, onChange, allowHogQL }: ColumnSelectProps): JSX.Element {
    // HogQL mode whenever the value isn't a real column name AND the field
    // allows it. Drop the `!!value` guard so the empty string (set by
    // picking "SQL expression" from the dropdown before typing anything)
    // still surfaces the SQL-expression label in the trigger instead of
    // rendering as blank.
    const isHogQL = allowHogQL && !options.some((o) => o.name === value)
    const displayValue = isHogQL ? HOGQL_SENTINEL : value
    return (
        <Select<string>
            value={displayValue || undefined}
            onValueChange={(v) => onChange((v === HOGQL_SENTINEL ? '' : (v as string)) ?? '')}
            itemToStringLabel={(o) => o ?? ''}
            itemToStringValue={(o) => o ?? ''}
        >
            <SelectTrigger render={(props) => <Button variant="outline" {...props} className="h-min" />}>
                <SelectValue placeholder="Select a value">
                    {(option: string | null) => {
                        if (!option) {
                            return null
                        }
                        if (option === HOGQL_SENTINEL) {
                            return (
                                <ItemContent variant="menuItem">
                                    <ItemTitle>SQL expression</ItemTitle>
                                    <ItemDescription className="leading-none">Use a HogQL expression</ItemDescription>
                                </ItemContent>
                            )
                        }
                        const opt = options.find((o) => o.name === option)
                        return (
                            <ItemContent variant="menuItem">
                                <ItemTitle>{option}</ItemTitle>
                                {opt?.type && <ItemDescription className="leading-none">{opt.type}</ItemDescription>}
                            </ItemContent>
                        )
                    }}
                </SelectValue>
            </SelectTrigger>
            <SelectContent className="min-w-(--anchor-width)" align="start" sideOffset={8}>
                <SelectGroup>
                    {options.map((o) => (
                        <SelectItem key={o.name} value={o.name} className="py-0">
                            <ItemContent variant="menuItem">
                                <ItemTitle>{o.name}</ItemTitle>
                                <ItemDescription className="leading-none">{o.type}</ItemDescription>
                            </ItemContent>
                        </SelectItem>
                    ))}
                    {allowHogQL && (
                        <SelectItem value={HOGQL_SENTINEL} className="py-0">
                            <ItemContent variant="menuItem">
                                <ItemTitle>SQL expression</ItemTitle>
                                <ItemDescription className="leading-none">Use a HogQL expression</ItemDescription>
                            </ItemContent>
                        </SelectItem>
                    )}
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
