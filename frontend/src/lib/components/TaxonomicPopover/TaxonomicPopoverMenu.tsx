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
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'

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
}: TaxonomicPopoverMenuProps<ValueType>): JSX.Element {
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
                type: groupType,
                getName: (t: any) => t?.name,
                getValue: (t: any) => t?.name ?? t?.id,
            },
            name: String(value),
        } as unknown as MenuFilterEntry
    }, [value, groupType])

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
                            type="secondary"
                            fullWidth
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
