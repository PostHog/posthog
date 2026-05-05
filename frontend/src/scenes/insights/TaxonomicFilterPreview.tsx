/**
 * Side-by-side preview of the legacy kea-driven TaxonomicFilter and the new
 * headless `TaxonomicAutocomplete` for visual / behavioural parity testing.
 *
 * Each entry in `SCENARIOS` mirrors a real prop combo we found in the wild
 * (Series, Breakdown, Cohort, Path target, Data warehouse, Property filter,
 * etc). The grid renders both the legacy panel and the new autocomplete for
 * each scenario, sharing selection state so we can confirm parity in:
 *   - which groups show up
 *   - which items are searchable / fetched
 *   - what `onChange` produces (group + value + name)
 *   - default seeding via controlled value or `defaultSelected`
 *
 * The `notes` field per scenario is a place to capture known UX gaps in the
 * new component — surface them now, fix in design pass.
 *
 * Mounted at the top of InsightAsScene when `isEditing` is true. Disposable —
 * delete this whole file once we flip the flag and the new path is the
 * default. Tracking removal in TAXONOMIC_FILTER_REWRITE_PRD.md (Phase 6).
 */
import { ReactNode, useState } from 'react'

import { IconChevronDown, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    ButtonGroup,
    DialogFooter,
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
    Textarea,
} from '@posthog/quill'

import {
    TaxonomicAutocomplete,
    TaxonomicAutocompleteConfigureState,
    TaxonomicFilterHeadless,
    useTaxonomicAutocomplete
} from 'lib/components/TaxonomicFilter/headless'
import {
    MenuFilterEntry,
    MenuFilterPreviewPane,
    TaxonomicFilterMenu,
} from 'lib/components/TaxonomicFilter/menu'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

interface SeriesSelection {
    groupType: TaxonomicFilterGroupType
    value: TaxonomicFilterValue
    name: string
}

interface ScenarioSelection {
    group: TaxonomicFilterGroupType
    value: TaxonomicFilterValue | null
    name?: string
    item?: any
}

interface Scenario {
    id: string
    label: string
    /** Real-world consumers that motivate this scenario. */
    consumers: string
    /** Known UX gaps in the new component for this scenario. */
    notes?: string
    groupTypes: TaxonomicFilterGroupType[]
    eventNames?: string[]
    suggestedFiltersLabel?: string
    showNumericalPropsOnly?: boolean
    allowNonCapturedEvents?: boolean
    enableKeywordShortcuts?: boolean
    minSearchQueryLength?: number
    excludedProperties?: Partial<Record<TaxonomicFilterGroupType, TaxonomicFilterValue[]>>
    defaultSeed?: SeriesSelection
    /** Mounted as a child of `<TaxonomicAutocomplete.Root>` — useful for ConfigureDialog. */
    extras?: ReactNode
}

const SCENARIOS: Scenario[] = [
    // {
    //     id: 'series',
    //     label: 'Series — events + actions',
    //     consumers: 'ActionFilterRow (Trends/Funnels/Retention/Stickiness)',
    //     groupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
    //     defaultSeed: {
    //         groupType: TaxonomicFilterGroupType.Events,
    //         value: '$pageview',
    //         name: '$pageview',
    //     },
    // },
    {
        id: 'series-dw',
        label: 'Series + Data Warehouse tables',
        consumers: 'ActionFilterRow when DWH series enabled',
        notes: 'DataWarehouse selection demands extra config (ID / Timestamp / Distinct ID columns). HogQL row also opens an editor sub-view. Both groups show the trailing chevron because they have a `<ConfigureView>` registered.',
        groupTypes: [
            TaxonomicFilterGroupType.Events,
            TaxonomicFilterGroupType.Actions,
            TaxonomicFilterGroupType.DataWarehouse,
            TaxonomicFilterGroupType.HogQLExpression,
            TaxonomicFilterGroupType.EventProperties,
            TaxonomicFilterGroupType.PersonProperties,
            TaxonomicFilterGroupType.SessionProperties,
            TaxonomicFilterGroupType.EventMetadata,
            TaxonomicFilterGroupType.EventFeatureFlags,
        ],
        extras: (
            <>
                <TaxonomicAutocomplete.ConfigureView
                    for={[TaxonomicFilterGroupType.DataWarehouse]}
                    title="Configure data warehouse table"
                >
                    {(state) => <DwhFieldsForm {...state} />}
                </TaxonomicAutocomplete.ConfigureView>
                <TaxonomicAutocomplete.ConfigureView
                    for={[TaxonomicFilterGroupType.HogQLExpression]}
                    title="Write SQL expression"
                >
                    {(state) => <HogQLExpressionForm {...state} />}
                </TaxonomicAutocomplete.ConfigureView>
            </>
        ),
    },
    // {
    //     id: 'hogql-only',
    //     label: 'HogQL expression',
    //     consumers: 'PathsHogQL, ad-hoc expression filters',
    //     groupTypes: [TaxonomicFilterGroupType.HogQLExpression],
    //     notes: 'Render-driven group: the row is a single sentinel that opens an expression editor sub-view. Real impl should swap the textarea for InlineHogQLEditor / Monaco.',
    //     extras: (
    //         <TaxonomicAutocomplete.ConfigureView
    //             for={[TaxonomicFilterGroupType.HogQLExpression]}
    //             title="Write SQL expression"
    //         >
    //             {(state) => <HogQLExpressionForm {...state} />}
    //         </TaxonomicAutocomplete.ConfigureView>
    //     ),
    // },
    {
        id: 'path-target',
        label: 'Path target — pageview / screen / custom',
        consumers: 'PathsTarget, PathsExclusions',
        groupTypes: [
            TaxonomicFilterGroupType.PageviewUrls,
            TaxonomicFilterGroupType.Screens,
            TaxonomicFilterGroupType.CustomEvents,
            TaxonomicFilterGroupType.Wildcards,
        ],
        eventNames: ['$pageview', '$screen', '$autocapture'],
        notes: 'Shortcut groups (PageviewUrls, Screens) only appear when the corresponding event is present in `eventNames`. Verify both pickers promote them to the front of the chip row.',
    },
    // {
    //     id: 'event-prop',
    //     label: 'Event property — single group',
    //     consumers: 'BoxPlotPropertySelector, PropertyValueMathSelector, replay filters',
    //     groupTypes: [TaxonomicFilterGroupType.EventProperties],
    //     notes: 'Each row has a "View →" cell. Right arrow → highlights View, Enter opens the details sheet (description / type / sent-as / pin). Driven by `<DetailsView>` + `useTaxonomicAutocompleteItemDetails`.',
    //     extras: (
    //         <TaxonomicAutocomplete.DetailsView
    //             for={[
    //                 TaxonomicFilterGroupType.EventProperties,
    //                 TaxonomicFilterGroupType.PersonProperties,
    //                 TaxonomicFilterGroupType.SessionProperties,
    //                 TaxonomicFilterGroupType.EventMetadata,
    //                 TaxonomicFilterGroupType.EventFeatureFlags,
    //             ]}
    //             title={(entry) => entry.friendlyLabel ?? entry.name}
    //         >
    //             {(state) => <PropertyDetails {...state} />}
    //         </TaxonomicAutocomplete.DetailsView>
    //     ),
    // },
    // {
    //     id: 'event-prop-numeric',
    //     label: 'Event property — numerical only',
    //     consumers: 'Math property selector (avg / sum / median)',
    //     notes: '`showNumericalPropsOnly={true}` filters to numeric properties. Verify the new picker forwards this via `getGroupListInput` (it already does — included for parity check).',
    //     groupTypes: [TaxonomicFilterGroupType.EventProperties],
    //     showNumericalPropsOnly: true,
    // },
    // {
    //     id: 'breakdown-trend',
    //     label: 'Breakdown (trend / funnel)',
    //     consumers: 'TaxonomicBreakdownPopover (default branch)',
    //     groupTypes: [
    //         TaxonomicFilterGroupType.EventProperties,
    //         TaxonomicFilterGroupType.PersonProperties,
    //         TaxonomicFilterGroupType.EventFeatureFlags,
    //         TaxonomicFilterGroupType.EventMetadata,
    //         TaxonomicFilterGroupType.CohortsWithAllUsers,
    //         TaxonomicFilterGroupType.SessionProperties,
    //         TaxonomicFilterGroupType.HogQLExpression,
    //         TaxonomicFilterGroupType.DataWarehouseProperties,
    //         TaxonomicFilterGroupType.DataWarehousePersonProperties,
    //     ],
    //     notes: 'HogQL row pops the expression editor sub-view. Same `<ConfigureView>` flow as DWH; commit({ value, name }) returns the expression as the selected item.',
    //     extras: (
    //         <TaxonomicAutocomplete.ConfigureView
    //             for={[TaxonomicFilterGroupType.HogQLExpression]}
    //             title="Write SQL expression"
    //         >
    //             {(state) => <HogQLExpressionForm {...state} />}
    //         </TaxonomicAutocomplete.ConfigureView>
    //     ),
    // },
    // {
    //     id: 'breakdown-retention',
    //     label: 'Breakdown (retention)',
    //     consumers: 'TaxonomicBreakdownPopover when query is RetentionQuery',
    //     groupTypes: [
    //         TaxonomicFilterGroupType.EventProperties,
    //         TaxonomicFilterGroupType.PersonProperties,
    //         TaxonomicFilterGroupType.EventFeatureFlags,
    //         TaxonomicFilterGroupType.CohortsWithAllUsers,
    //         TaxonomicFilterGroupType.DataWarehousePersonProperties,
    //     ],
    // },
    // {
    //     id: 'breakdown-cohort-only',
    //     label: 'Cohort breakdown — single group',
    //     consumers: 'TaxonomicBreakdownPopover when CohortsWithAllUsers chosen',
    //     groupTypes: [TaxonomicFilterGroupType.CohortsWithAllUsers],
    //     notes: 'When only one group is in the set, "All" + that one chip is redundant. Maybe collapse to no-chip mode automatically.',
    // },
    // {
    //     id: 'flag-conditions',
    //     label: 'Feature flag release conditions',
    //     consumers: 'FeatureFlagReleaseConditions',
    //     groupTypes: [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.Cohorts],
    // },
    // {
    //     id: 'replay-filters',
    //     label: 'Recordings universal filters',
    //     consumers: 'RecordingsUniversalFiltersEmbed, replay templates',
    //     groupTypes: [
    //         TaxonomicFilterGroupType.Replay,
    //         TaxonomicFilterGroupType.Events,
    //         TaxonomicFilterGroupType.Actions,
    //         TaxonomicFilterGroupType.EventProperties,
    //         TaxonomicFilterGroupType.PersonProperties,
    //         TaxonomicFilterGroupType.SessionProperties,
    //         TaxonomicFilterGroupType.Cohorts,
    //     ],
    // },
    // {
    //     id: 'dwh-tables',
    //     label: 'Data warehouse table picker',
    //     consumers: 'time_to_see_data, ActionFilterRow (DWH series)',
    //     groupTypes: [TaxonomicFilterGroupType.DataWarehouse],
    //     notes: 'Same ConfigureDialog flow as the Series + DWH scenario, single-group form.',
    //     extras: (
    //         <TaxonomicAutocomplete.ConfigureView
    //             for={[TaxonomicFilterGroupType.DataWarehouse]}
    //             title="Configure data warehouse table"
    //         >
    //             {(state) => <DwhFieldsForm {...state} />}
    //         </TaxonomicAutocomplete.ConfigureView>
    //     ),
    // },
    // {
    //     id: 'allow-non-captured',
    //     label: 'Events — allow non-captured',
    //     consumers: 'NotebookNodeQuery, hogql etc.',
    //     groupTypes: [TaxonomicFilterGroupType.Events],
    //     allowNonCapturedEvents: true,
    //     notes: 'Should let user type a fresh event name and pick it as a "new event" row.',
    // },
    // {
    //     id: 'excluded-props',
    //     label: 'Event properties with exclusions',
    //     consumers: 'ActionFilterRow excludedProperties prop',
    //     groupTypes: [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties],
    //     excludedProperties: {
    //         [TaxonomicFilterGroupType.EventProperties]: ['$browser', '$os'],
    //     },
    // },
    // {
    //     id: 'min-search',
    //     label: 'Min search query length',
    //     consumers: 'Inline events sub-search (3-char minimum)',
    //     groupTypes: [TaxonomicFilterGroupType.Events],
    //     minSearchQueryLength: 3,
    //     notes: 'Empty state should read "Type more to search" until 3 chars; new picker already supports this via the same input.',
    // },
    // {
    //     id: 'wide-insight',
    //     label: 'Insight property kitchen sink',
    //     consumers: 'PropertyFilters in dashboards / insights',
    //     groupTypes: [
    //         TaxonomicFilterGroupType.EventProperties,
    //         TaxonomicFilterGroupType.PersonProperties,
    //         TaxonomicFilterGroupType.EventFeatureFlags,
    //         TaxonomicFilterGroupType.EventMetadata,
    //         TaxonomicFilterGroupType.Cohorts,
    //         TaxonomicFilterGroupType.SessionProperties,
    //         TaxonomicFilterGroupType.HogQLExpression,
    //     ],
    // },
]

export function TaxonomicFilterPreview(): JSX.Element {
    return (
        <div className="border border-dashed border-warning-light rounded p-3 bg-surface-primary">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold m-0">TaxonomicFilter — variation preview</h3>
                <span className="text-xxs text-secondary">
                    Disposable. Each card mirrors a real prop combo. Notes call out UX gaps in the new picker.
                </span>
            </div>

            <SeriesParityCard />

            <div className="grid grid-cols-1 @4xl/scene:grid-cols-2 gap-128 mt-3">
                {SCENARIOS.map((scenario) => (
                    <ScenarioCard key={scenario.id} scenario={scenario} />
                ))}
            </div>
        </div>
    )
}

/**
 * Bridges the old headless autocomplete's transient highlight state into
 * the new menu's `MenuFilterPreviewPane` so the two components share the
 * same preview UI without copying its layout into the headless module.
 */
function OldHeadlessPreviewBridge(): JSX.Element {
    const { highlightedEntry } = useTaxonomicAutocomplete()
    return (
        <MenuFilterPreviewPane
            entry={highlightedEntry}
            className="hidden md:flex flex-col w-[300px] shrink-0 min-w-0 border-l"
        />
    )
}

function ScenarioCard({ scenario }: { scenario: Scenario }): JSX.Element {
    const [legacy, setLegacy] = useState<ScenarioSelection | null>(null)
    const [autocomplete, setAutocomplete] = useState<ScenarioSelection | null>(null)
    // Track the menu rebuild's selection so re-opening the trigger jumps
    // straight back into the panel that owns it (HogQL editor pre-fill,
    // DWH config restore, drilled combobox).
    const [menuSelected, setMenuSelected] = useState<MenuFilterEntry | null>(null)

    const handle =
        (setter: (s: ScenarioSelection | null) => void) =>
        (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any): void => {
            setter({ group: group.type, value, name: item?.name, item })
        }

    return (
        <div className="border rounded p-2 flex flex-col gap-2">
            <header className="flex items-baseline justify-between gap-2 flex-wrap">
                <h4 className="text-sm font-semibold m-0">{scenario.label}</h4>
                <span className="text-xxs text-secondary">{scenario.consumers}</span>
            </header>

            {scenario.notes && (
                <div className="text-xxs leading-tight bg-surface-secondary border border-warning-light/40 rounded px-2 py-1">
                    <span className="font-semibold text-warning">UX gap: </span>
                    {scenario.notes}
                </div>
            )}

            <div className="grid grid-cols-3 gap-2">
                <div>
                    <div className="text-xxs text-secondary mb-1">Legacy panel</div>
                    <TaxonomicFilter
                        taxonomicFilterLogicKey={`scenario-${scenario.id}`}
                        taxonomicGroupTypes={scenario.groupTypes}
                        eventNames={scenario.eventNames}
                        suggestedFiltersLabel={scenario.suggestedFiltersLabel}
                        showNumericalPropsOnly={scenario.showNumericalPropsOnly}
                        allowNonCapturedEvents={scenario.allowNonCapturedEvents}
                        enableKeywordShortcuts={scenario.enableKeywordShortcuts}
                        minSearchQueryLength={scenario.minSearchQueryLength}
                        excludedProperties={scenario.excludedProperties}
                        onChange={handle(setLegacy)}
                        width={320}
                        height={320}
                    />
                </div>
                <div>
                    <div className="text-xxs text-secondary mb-1">Old headless (autocomplete)</div>
                    <TaxonomicFilterHeadless.Root
                        bindRootProps={false}
                        taxonomicGroupTypes={scenario.groupTypes}
                        eventNames={scenario.eventNames}
                        suggestedFiltersLabel={scenario.suggestedFiltersLabel}
                        showNumericalPropsOnly={scenario.showNumericalPropsOnly}
                        allowNonCapturedEvents={scenario.allowNonCapturedEvents}
                        enableKeywordShortcuts={scenario.enableKeywordShortcuts}
                        minSearchQueryLength={scenario.minSearchQueryLength}
                        excludedProperties={scenario.excludedProperties}
                        onChange={handle(setAutocomplete)}
                    >
                        <TaxonomicAutocomplete.Root
                            triggerLabel={scenario.label}
                            defaultSelected={
                                scenario.defaultSeed
                                    ? {
                                          groupType: scenario.defaultSeed.groupType,
                                          value: scenario.defaultSeed.value,
                                          name: scenario.defaultSeed.name,
                                      }
                                    : null
                            }
                        >
                            <TaxonomicAutocomplete.Popover>
                                <TaxonomicAutocomplete.MenuTrigger />
                                <TaxonomicAutocomplete.Content className="!w-[720px] !min-w-[720px]">
                                    <TaxonomicAutocomplete.Header rootTitle={scenario.label} />
                                    <TaxonomicAutocomplete.RootView>
                                        <div className="flex flex-1 min-h-0">
                                            <div className="flex flex-col flex-1 min-w-0 min-h-0">
                                                <div className="p-1">
                                                    <TaxonomicAutocomplete.Input />
                                                </div>
                                                <TaxonomicAutocomplete.Chips />
                                                <TaxonomicAutocomplete.List />
                                            </div>
                                            <OldHeadlessPreviewBridge />
                                        </div>
                                    </TaxonomicAutocomplete.RootView>
                                    {scenario.extras}
                                </TaxonomicAutocomplete.Content>
                            </TaxonomicAutocomplete.Popover>
                        </TaxonomicAutocomplete.Root>
                    </TaxonomicFilterHeadless.Root>
                </div>
                <div>
                    <div className="text-xxs text-secondary mb-1">New menu (rebuild)</div>
                    <TaxonomicFilterHeadless.Root
                        bindRootProps={false}
                        taxonomicGroupTypes={scenario.groupTypes}
                        eventNames={scenario.eventNames}
                        suggestedFiltersLabel={scenario.suggestedFiltersLabel}
                        showNumericalPropsOnly={scenario.showNumericalPropsOnly}
                        allowNonCapturedEvents={scenario.allowNonCapturedEvents}
                        enableKeywordShortcuts={scenario.enableKeywordShortcuts}
                        minSearchQueryLength={scenario.minSearchQueryLength}
                        excludedProperties={scenario.excludedProperties}
                        onChange={handle(setAutocomplete)}
                    >
                        <TaxonomicFilterMenu
                            triggerLabel={scenario.label}
                            selected={menuSelected}
                            onCommit={(entry) => setMenuSelected(entry)}
                        />
                    </TaxonomicFilterHeadless.Root>
                </div>
            </div>

            <footer className="grid grid-cols-2 gap-2 text-[11px] border-t pt-2 mt-1">
                <SelectionEcho label="Legacy" state={legacy} />
                <SelectionEcho label="Autocomplete" state={autocomplete} />
            </footer>
        </div>
    )
}

/**
 * Field-mapping form for the DataWarehouse `<ConfigureView>` demo. Mirrors
 * the legacy popover (ID / Timestamp / Distinct ID) using Quill `<Field>` +
 * `<Select>` primitives. `commit(extra)` merges these into the underlying
 * item before it reaches the consumer's `onChange`.
 */
interface DwhColumnOption {
    name: string
    /** Underlying SQL type for the column (e.g. `integer`, `string`). */
    type?: string
}

function DwhFieldsForm({ entry, commit, cancel }: TaxonomicAutocompleteConfigureState): JSX.Element {
    const tableName = entry.name
    const fieldsRecord = ((entry.item as { fields?: Record<string, { name: string; type?: string }> })?.fields ??
        {}) as Record<string, { name?: string; type?: string }>
    const columns: DwhColumnOption[] = Object.entries(fieldsRecord).map(([name, field]) => ({
        name,
        type: field?.type,
    }))

    // Pick the best-matching column, falling back to the first column so the
    // form has sensible defaults even when the table lacks the conventional
    // names (e.g. `extended_properties` which has no timestamp / distinct_id).
    const guess = (predicate: (col: string) => boolean): DwhColumnOption | null =>
        columns.find((c) => predicate(c.name)) ?? columns[0] ?? null

    const [idField, setIdField] = useState<DwhColumnOption | null>(() => guess((c) => c === 'id' || c.endsWith('_id')))
    const [timestampField, setTimestampField] = useState<DwhColumnOption | null>(() =>
        guess((c) => c === 'timestamp' || c.includes('time') || c.includes('created') || c.includes('date'))
    )
    const [distinctIdField, setDistinctIdField] = useState<DwhColumnOption | null>(() =>
        guess((c) => c.includes('distinct'))
    )

    const canSubmit = !!idField && !!timestampField && !!distinctIdField

    return (
        <div className="flex flex-col flex-1">
            <div className="flex flex-col gap-4 p-2 flex-1">
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
            <DialogFooter>
                <Button variant="outline" onClick={cancel}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    disabled={!canSubmit}
                    onClick={() =>
                        commit({
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
    )
}

/**
 * HogQL editor for the `<ConfigureView>` demo. Quill `<Field>` + `<Textarea>`.
 * Real impl should swap the textarea for the existing `InlineHogQLEditor` /
 * Monaco wrapper. `commit` merges the expression into the item — the
 * orchestrator's `onChange` receives `{ name: <expr>, value: <expr> }`.
 */
function HogQLExpressionForm({ entry, commit, cancel }: TaxonomicAutocompleteConfigureState): JSX.Element {
    const initial =
        typeof entry.item === 'object' && entry.item && 'value' in entry.item
            ? String((entry.item as { value?: unknown }).value ?? '')
            : ''
    const [expression, setExpression] = useState(initial)
    return (
        <div className="flex flex-col flex-1">
            <div className="flex flex-col gap-4 p-2 flex-1">
                <Field>
                    <FieldLabel>Expression</FieldLabel>
                    <FieldContent>
                        <Textarea
                            autoFocus
                            rows={4}
                            value={expression}
                            onChange={(e) => setExpression(e.target.value)}
                            placeholder="properties.$browser = 'Chrome'"
                            className="font-mono text-xxs"
                        />
                        <FieldDescription>
                            Returns this expression as the selected value. Esc goes back without saving.
                        </FieldDescription>
                    </FieldContent>
                </Field>
            </div>
            <DialogFooter>
                <Button variant="outline" onClick={cancel}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    disabled={!expression.trim()}
                    onClick={() => commit({ name: expression, value: expression })}
                >
                    Save
                </Button>
            </DialogFooter>
        </div>
    )
}

/**
 * Required column-picker built on Quill `<Field>` + `<Select>` with object
 * values (base-ui supports any value, not just strings — see
 * https://base-ui.com/react/components/select#object-values). The selected
 * row + each option render via Quill `<ItemContent>` so we can show the
 * column type as a description, like the legacy DWH popover.
 */
function ColumnField({
    label,
    value,
    onValueChange,
    options,
}: {
    label: string
    value: DwhColumnOption | null
    onValueChange: (v: DwhColumnOption | null) => void
    options: DwhColumnOption[]
}): JSX.Element {
    return (
        <Field>
            <FieldLabel>
                {label} <span className="text-danger">*</span>
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

function SelectionEcho({ label, state }: { label: string; state: ScenarioSelection | null }): JSX.Element {
    if (!state) {
        return <div className="text-secondary">{label}: —</div>
    }
    return (
        <div>
            <span className="text-secondary">{label}: </span>
            <code>{state.group}</code> / <code>{String(state.value)}</code>
            {state.name ? <span className="text-secondary"> ({state.name})</span> : null}
        </div>
    )
}

const SERIES_GROUP_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.Actions,
]

const SERIES_DEFAULT: SeriesSelection = {
    groupType: TaxonomicFilterGroupType.Events,
    value: '$pageview',
    name: '$pageview',
}

/**
 * Sibling clear button for ButtonGroup-wrapped triggers. Lives outside the
 * `<TaxonomicAutocomplete.Trigger>` so the trigger renders a single
 * `<button>` (and Tab order on the page works), while still hooking into
 * the same `Root` for `selected` / `clearSelection`.
 */
function SeriesParityClearButton(): JSX.Element | null {
    const { selectedEntry, clearSelection } = useTaxonomicAutocomplete()
    if (!selectedEntry) {
        return null
    }
    return (
        <Button
            type="button"
            variant="outline"
            aria-label="Clear selection"
            onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                e.stopPropagation()
                clearSelection()
            }}
        >
            <IconX />
        </Button>
    )
}

function SeriesParityCard(): JSX.Element {
    const [series, setSeries] = useState<SeriesSelection>(SERIES_DEFAULT)
    const [autocompleteSeedKey, setAutocompleteSeedKey] = useState(0)

    return (
        <div className="border rounded p-2">
            <header className="flex items-baseline justify-between mb-2">
                <h4 className="text-sm font-semibold m-0">Series parity (trigger-only)</h4>
                <span className="text-xxs text-secondary">
                    Both pickers share <code>{`{ groupType, value, name }`}</code>; default <code>$pageview</code>.
                </span>
            </header>
            <div className="flex items-center gap-3 flex-wrap">
                <div className="flex flex-col gap-1">
                    <span className="text-xxs text-secondary">Legacy TaxonomicPopover</span>
                    <TaxonomicPopover
                        data-attr="series-parity-legacy"
                        type="secondary"
                        groupType={series.groupType}
                        value={series.value}
                        groupTypes={SERIES_GROUP_TYPES}
                        placeholder="Select series"
                        renderValue={() => <span>{series.name}</span>}
                        onChange={(value, groupType, item) => {
                            if (value === null) {
                                return
                            }
                            setSeries({
                                groupType,
                                value,
                                name: (item?.name as string | undefined) ?? String(value),
                            })
                            setAutocompleteSeedKey((k) => k + 1)
                        }}
                    />
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-xxs text-secondary">New TaxonomicAutocomplete</span>
                    <TaxonomicFilterHeadless.Root
                        bindRootProps={false}
                        taxonomicGroupTypes={SERIES_GROUP_TYPES}
                        onChange={(group, value, item) => {
                            if (value === null) {
                                return
                            }
                            setSeries({
                                groupType: group.type,
                                value,
                                name: (item?.name as string | undefined) ?? String(value),
                            })
                        }}
                    >
                        <TaxonomicAutocomplete.Root
                            key={autocompleteSeedKey}
                            triggerLabel="Select series"
                            defaultSelected={{
                                groupType: series.groupType,
                                value: series.value,
                                name: series.name,
                            }}
                        >
                            <TaxonomicAutocomplete.Popover>
                                {/* `ButtonGroup` wraps Trigger + clear so PopoverTrigger renders a
                                    single `<button>`. Wrapping ButtonGroup *inside* Trigger makes
                                    base-ui inject trigger props (id, tabIndex, click) onto the
                                    ButtonGroup div — that breaks Tab order on the page since the
                                    div becomes a focusable trigger. */}
                                <ButtonGroup>
                                    <TaxonomicAutocomplete.Trigger>
                                        {({ selected, label, open }) => (
                                            <Button
                                                type="button"
                                                variant="outline"
                                                data-state={open ? 'open' : 'closed'}
                                                className="justify-between gap-2"
                                            >
                                                <span className="flex items-center gap-2">
                                                    <span className={selected ? '' : 'text-muted-foreground'}>
                                                        {label}
                                                    </span>
                                                    {selected && (
                                                        <span className="text-xxs uppercase tracking-wide text-muted-foreground">
                                                            in {selected.group.name}
                                                        </span>
                                                    )}
                                                </span>
                                            </Button>
                                        )}
                                    </TaxonomicAutocomplete.Trigger>
                                    <SeriesParityClearButton />
                                </ButtonGroup>
                                <TaxonomicAutocomplete.Content>
                                    <TaxonomicAutocomplete.Header rootTitle="Select series" />
                                    <TaxonomicAutocomplete.RootView>
                                        <div className="p-1">
                                            <TaxonomicAutocomplete.Input />
                                        </div>
                                        <TaxonomicAutocomplete.Chips />
                                        <TaxonomicAutocomplete.List />
                                    </TaxonomicAutocomplete.RootView>
                                </TaxonomicAutocomplete.Content>
                            </TaxonomicAutocomplete.Popover>
                        </TaxonomicAutocomplete.Root>
                    </TaxonomicFilterHeadless.Root>
                </div>

                <div className="flex flex-col gap-1">
                    <span className="text-xxs text-secondary">LemonButton-styled trigger</span>
                    <TaxonomicFilterHeadless.Root
                        bindRootProps={false}
                        taxonomicGroupTypes={SERIES_GROUP_TYPES}
                        onChange={(group, value, item) => {
                            if (value === null) {
                                return
                            }
                            setSeries({
                                groupType: group.type,
                                value,
                                name: (item?.name as string | undefined) ?? String(value),
                            })
                        }}
                    >
                        <TaxonomicAutocomplete.Root
                            key={`lb-${autocompleteSeedKey}`}
                            triggerLabel="Select series"
                            defaultSelected={{
                                groupType: series.groupType,
                                value: series.value,
                                name: series.name,
                            }}
                        >
                            <TaxonomicAutocomplete.Popover>
                                <TaxonomicAutocomplete.Trigger>
                                    {({ selected, label, open }) => (
                                        <LemonButton
                                            type="secondary"
                                            data-attr="series-parity-autocomplete"
                                            aria-expanded={open}
                                            sideIcon={<IconChevronDown />}
                                        >
                                            <span className={selected ? '' : 'text-secondary'}>{label}</span>
                                        </LemonButton>
                                    )}
                                </TaxonomicAutocomplete.Trigger>
                                <TaxonomicAutocomplete.Content>
                                    <TaxonomicAutocomplete.Header rootTitle="Select series" />
                                    <TaxonomicAutocomplete.RootView>
                                        <div className="p-1">
                                            <TaxonomicAutocomplete.Input />
                                        </div>
                                        <TaxonomicAutocomplete.Chips />
                                        <TaxonomicAutocomplete.List />
                                    </TaxonomicAutocomplete.RootView>
                                </TaxonomicAutocomplete.Content>
                            </TaxonomicAutocomplete.Popover>
                        </TaxonomicAutocomplete.Root>
                    </TaxonomicFilterHeadless.Root>
                </div>

                <div className="ml-auto text-xxs">
                    Shared: <code>{series.groupType}</code> / <code>{String(series.value)}</code> ({series.name})
                </div>
            </div>
        </div>
    )
}
