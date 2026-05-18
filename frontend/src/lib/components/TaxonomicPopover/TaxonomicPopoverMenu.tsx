/**
 * Central bridge from the legacy `TaxonomicPopover` API to the rebuilt
 * `TaxonomicFilterMenu` (dropdown + preview-pane UI).
 *
 * `TaxonomicPopover` renders this alongside the legacy popover whenever the
 * `taxonomic-filter-menu-rebuild` flag is on, so every popover call site can
 * be compared against the new picker without per-site wiring.
 *
 * The adapter translates `TaxonomicPopover`'s `(value, groupType, item)`
 * shape into the headless orchestrator + menu:
 *   - `value` → a synthetic `MenuFilterEntry` so the trigger reflects the
 *     current selection and re-opening routes into the right panel.
 *   - the headless `onChange(group, value, item)` → the legacy
 *     `onChange(value, groupType, item)`.
 */
import { useMemo } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterEntry, TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu'
import {
    DataWarehousePopoverField,
    ExcludedProperties,
    SelectedProperties,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'

/**
 * Shortcut/aggregator groups that have no real items of their own — a
 * selection never genuinely "belongs" to one. `TaxonomicPopover.groupType`
 * often defaults to `SuggestedFilters` (e.g. the insights series picker),
 * so a synthetic entry stamped with it would lock the combobox to that
 * near-empty group instead of opening on the value's real category.
 */
const NON_SELECTABLE_GROUP_TYPES: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
    TaxonomicFilterGroupType.Empty,
])

export interface TaxonomicPopoverMenuProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType | null
    groupTypes?: TaxonomicFilterGroupType[]
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any) => void
    renderValue?: (value: ValueType) => JSX.Element | null
    placeholder?: React.ReactNode
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    metadataSource?: AnyDataNode
    excludedProperties?: ExcludedProperties
    selectedProperties?: SelectedProperties
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
    allowNonCapturedEvents?: boolean
    suggestedFiltersLabel?: string
    enableKeywordShortcuts?: boolean
    disabledReason?: string
    /** Trigger button styling, forwarded so the rebuilt menu's trigger
     *  matches the legacy `TaxonomicPopover` button at the call site. */
    fullWidth?: boolean
    size?: LemonButtonProps['size']
    triggerType?: LemonButtonProps['type']
}

export function TaxonomicPopoverMenu<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>({
    groupType,
    value,
    groupTypes,
    onChange,
    renderValue,
    placeholder = 'Please select',
    eventNames = [],
    schemaColumns,
    metadataSource,
    excludedProperties,
    selectedProperties,
    showNumericalPropsOnly,
    dataWarehousePopoverFields,
    maxContextOptions,
    allowNonCapturedEvents,
    suggestedFiltersLabel,
    enableKeywordShortcuts,
    disabledReason,
    fullWidth = true,
    size,
    triggerType = 'secondary',
}: TaxonomicPopoverMenuProps<ValueType>): JSX.Element {
    // The group a synthetic `selected` entry should claim. `groupType` is
    // the popover's *default tab*, not the value's real category — and it's
    // often a non-selectable shortcut group. Fall back to the first real
    // group in `groupTypes` so the menu opens on a browsable category.
    const selectedGroupType = useMemo<TaxonomicFilterGroupType>(() => {
        if (!NON_SELECTABLE_GROUP_TYPES.has(groupType)) {
            return groupType
        }
        return (groupTypes ?? []).find((t) => !NON_SELECTABLE_GROUP_TYPES.has(t)) ?? groupType
    }, [groupType, groupTypes])

    // Synthetic entry — the menu reads `group.type` to route the initial
    // open and `name` to highlight the matching row. A full
    // `TaxonomicFilterGroup` isn't needed; the orchestrator's resolved group
    // is used once the user commits.
    const selected = useMemo<MenuFilterEntry | null>(() => {
        if (value == null || value === '') {
            return null
        }
        return {
            item: { id: value, name: String(value) },
            group: {
                type: selectedGroupType,
                getName: (t: any) => t?.name,
                getValue: (t: any) => t?.name ?? t?.id,
            },
            name: String(value),
        } as unknown as MenuFilterEntry
    }, [value, selectedGroupType])

    return (
        <TaxonomicFilterHeadless.Root
            // Skip the legacy rootProps keydown handler — it intercepts
            // Tab/Arrow for the old list UI we don't render here.
            bindRootProps={false}
            taxonomicGroupTypes={groupTypes ?? [groupType]}
            groupType={groupType}
            value={value ?? undefined}
            eventNames={eventNames}
            schemaColumns={schemaColumns}
            metadataSource={metadataSource}
            excludedProperties={excludedProperties}
            selectedProperties={selectedProperties}
            showNumericalPropsOnly={showNumericalPropsOnly}
            maxContextOptions={maxContextOptions}
            allowNonCapturedEvents={allowNonCapturedEvents}
            suggestedFiltersLabel={suggestedFiltersLabel}
            enableKeywordShortcuts={enableKeywordShortcuts}
            onChange={(group, changedValue, item) => onChange(changedValue as ValueType, group.type, item)}
        >
            <TaxonomicFilterMenu
                selected={selected}
                dataWarehousePopoverFields={dataWarehousePopoverFields}
                trigger={({ open }) => (
                    // base-ui's DropdownMenuTrigger spreads its props onto
                    // this wrapper; the LemonButton inside is presentational.
                    // Mirrors the proven ActionFilterRow series-picker trigger.
                    <div className="relative inline-flex min-w-0">
                        <LemonButton
                            type={triggerType}
                            fullWidth={fullWidth}
                            size={size}
                            active={open}
                            disabledReason={disabledReason}
                            sideIcon={<IconChevronDown />}
                            data-attr="taxonomic-popover-menu-trigger"
                        >
                            {value ? (
                                (renderValue?.(value) ?? <span>{String(value)}</span>)
                            ) : (
                                <span className="text-secondary">{placeholder}</span>
                            )}
                        </LemonButton>
                    </div>
                )}
            />
        </TaxonomicFilterHeadless.Root>
    )
}
