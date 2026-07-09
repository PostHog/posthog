/**
 * Central bridge from the legacy `TaxonomicPopover` API to the rebuilt
 * `TaxonomicFilterMenu` (dropdown + preview-pane UI).
 *
 * `TaxonomicPopover` renders this whenever the `taxonomic-filter-menu-rebuild`
 * flag is on and the user prefers the new menu, at every popover call site.
 *
 * The adapter translates `TaxonomicPopover`'s `(value, groupType, item)`
 * shape into the headless orchestrator + menu:
 *   - `value` → a synthetic `MenuFilterEntry` so the trigger reflects the
 *     current selection and re-opening routes into the right panel.
 *   - the headless `onChange(group, value, item)` → the legacy
 *     `onChange(value, groupType, item, group)`.
 *
 * Lazy mount: the headless orchestrator (`buildTaxonomicGroups` + several
 * kea subscriptions) is expensive and the picker is rendered at many call
 * sites. So until the user first clicks the trigger, only a lightweight
 * placeholder button is rendered — the heavy `ArmedTaxonomicPopoverMenu` is
 * mounted on first click and opened immediately via `defaultOpen`.
 */
import { useValues } from 'kea'
import { ReactElement, useMemo, useState } from 'react'

import { IconChevronDown, IconFilter } from '@posthog/icons'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { MenuFilterEntry, TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu'
import { MenuInputTrigger } from 'lib/components/TaxonomicFilter/menu/InputTrigger'
import { taxonomicTriggerWrapperClassName } from 'lib/components/TaxonomicFilter/menu/triggerLayout'
import {
    AllowedProperties,
    DataWarehousePopoverField,
    ExcludedProperties,
    SelectedProperties,
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'

import { TaxonomicMenuToggle } from './TaxonomicMenuToggle'

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

type TriggerButtonProps = Pick<
    LemonButtonProps,
    'icon' | 'sideIcon' | 'fullWidth' | 'size' | 'type' | 'className' | 'disabledReason' | 'truncate'
>

export interface TaxonomicPopoverMenuProps<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue> {
    groupType: TaxonomicFilterGroupType
    value?: ValueType | null
    groupTypes?: TaxonomicFilterGroupType[]
    /** The 4th arg is the orchestrator's resolved group — consumers that
     *  need the full `TaxonomicFilterGroup` (not just its type) can use it. */
    onChange: (value: ValueType, groupType: TaxonomicFilterGroupType, item: any, group: TaxonomicFilterGroup) => void
    renderValue?: (value: ValueType) => JSX.Element | null
    placeholder?: React.ReactNode
    placeholderClass?: string
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    metadataSource?: AnyDataNode
    excludedProperties?: ExcludedProperties
    selectedProperties?: SelectedProperties
    propertyAllowList?: AllowedProperties
    optionsFromProp?: Partial<Record<TaxonomicFilterGroupType, SimpleOption[]>>
    hideBehavioralCohorts?: boolean
    endpointFilters?: Record<string, any>
    hogQLGlobals?: Record<string, any>
    showNumericalPropsOnly?: boolean
    dataWarehousePopoverFields?: DataWarehousePopoverField[]
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
    allowNonCapturedEvents?: boolean
    suggestedFiltersLabel?: string
    enableKeywordShortcuts?: boolean
    /** Trigger button styling, forwarded so the rebuilt menu's trigger
     *  matches the legacy `TaxonomicPopover` button at the call site. */
    triggerButtonProps?: TriggerButtonProps
    /**
     * `'input'` renders a replay-style search box + filter-icon trigger
     * instead of a single button, while no value is selected. Focusing the
     * box opens the combobox; clicking the icon opens the dropdown menu.
     */
    triggerVariant?: 'button' | 'input'
}

/**
 * Builds the trigger `LemonButton` element — shared by the lazy placeholder
 * and the live menu trigger so the two are visually identical. Returns a
 * bare `LemonButton` (no wrapper) so base-ui's `DropdownMenuTrigger` can
 * render onto it directly and the DOM matches a plain button.
 */
function buildTriggerButton(args: {
    value: TaxonomicFilterValue | null | undefined
    renderValue?: (value: any) => JSX.Element | null
    placeholder?: React.ReactNode
    placeholderClass?: string
    triggerButtonProps?: TriggerButtonProps
    open?: boolean
    onClick?: () => void
}): ReactElement {
    const { value, renderValue, placeholder, placeholderClass, triggerButtonProps, open, onClick } = args
    return (
        <LemonButton
            type="secondary"
            {...triggerButtonProps}
            // LemonButton only auto-adds the dropdown chevron inside a
            // LemonDropdown; this trigger isn't, so default it explicitly
            // (legacy parity). A caller passing `sideIcon={null}` still
            // suppresses it.
            sideIcon={triggerButtonProps?.sideIcon === undefined ? <IconChevronDown /> : triggerButtonProps.sideIcon}
            active={open}
            onClick={onClick}
            data-attr="taxonomic-popover-menu-trigger"
        >
            {value ? (
                (renderValue?.(value) ?? <span>{String(value)}</span>)
            ) : (
                <span className={placeholderClass ?? 'text-secondary'}>{placeholder}</span>
            )}
        </LemonButton>
    )
}

export function TaxonomicPopoverMenu<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>(
    props: TaxonomicPopoverMenuProps<ValueType>
): JSX.Element {
    // Lazy mount — until the user first clicks the trigger, render only the
    // placeholder button. Mounting the orchestrator for pickers the user
    // never opens would multiply mount cost across every call site on a page.
    const [armed, setArmed] = useState(false)
    // Which panel the first interaction should land on once armed. The input
    // variant has two entry points (search box → combobox, icon → menu); the
    // button variant always resolves its own open state, so this is ignored.
    const [armOpenTo, setArmOpenTo] = useState<'menu' | 'combobox'>('combobox')

    const { value, renderValue, placeholder = 'Select', placeholderClass, triggerButtonProps, triggerVariant } = props
    const useInputTrigger = triggerVariant === 'input' && (value == null || value === '')

    if (armed) {
        return <ArmedTaxonomicPopoverMenu {...props} defaultOpenState={useInputTrigger ? armOpenTo : undefined} />
    }

    const arm = (to: 'menu' | 'combobox'): void => {
        setArmOpenTo(to)
        setArmed(true)
    }

    return (
        // data-lemon-skin: the armed trigger's wrapper carries it, so the
        // resting placeholder must too — the skin's geometry corrections
        // (lemon-skin.scss) apply identically to both states.
        <span data-lemon-skin className={taxonomicTriggerWrapperClassName(triggerButtonProps?.fullWidth)}>
            {useInputTrigger ? (
                <MenuInputTrigger
                    iconButton={
                        // Keep the resting placeholder visually identical to the armed trigger.
                        // data-attr differs from the armed trigger's — intentional for analytics.
                        <LemonButton
                            size="small"
                            icon={<IconFilter />}
                            aria-label="Open filter menu"
                            data-attr="taxonomic-popover-menu-trigger"
                            // Stop the click bubbling to the LemonInput wrapper, whose
                            // onClick focuses the input, whose onFocus arms the combobox.
                            // Without this the icon would open the combobox, not the menu.
                            onClick={(e) => {
                                e.stopPropagation()
                                arm('menu')
                            }}
                        />
                    }
                    fullWidth={!!triggerButtonProps?.fullWidth}
                    placeholder={typeof placeholder === 'string' ? placeholder : 'Add filter'}
                    onFocus={() => arm('combobox')}
                />
            ) : (
                buildTriggerButton({
                    value,
                    renderValue,
                    placeholder,
                    placeholderClass,
                    triggerButtonProps,
                    onClick: () => setArmed(true),
                })
            )}
            <TaxonomicMenuToggle />
        </span>
    )
}

function ArmedTaxonomicPopoverMenu<ValueType extends TaxonomicFilterValue = TaxonomicFilterValue>({
    groupType,
    value,
    groupTypes,
    onChange,
    renderValue,
    placeholder = 'Select',
    placeholderClass,
    eventNames = [],
    schemaColumns,
    metadataSource,
    excludedProperties,
    selectedProperties,
    propertyAllowList,
    optionsFromProp,
    hideBehavioralCohorts,
    endpointFilters,
    hogQLGlobals,
    showNumericalPropsOnly,
    dataWarehousePopoverFields,
    maxContextOptions,
    allowNonCapturedEvents,
    suggestedFiltersLabel,
    enableKeywordShortcuts,
    triggerButtonProps,
    triggerVariant,
    defaultOpenState,
}: TaxonomicPopoverMenuProps<ValueType> & { defaultOpenState?: 'menu' | 'combobox' }): JSX.Element {
    // Data warehouse tables carry their column schema (`fields`) in
    // `databaseTableListLogic`, not in the bare popover value — needed so
    // the DWH config form can render its column dropdowns / preview. Read
    // here (not in the lazy outer component) so non-opened pickers don't
    // subscribe to it.
    const { dataWarehouseTablesMap } = useValues(databaseTableListLogic)

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
    // is used once the user commits. For a data warehouse value, merge in
    // the resolved table schema so re-opening lands on a populated config
    // form (column dropdowns, preview) rather than an empty one.
    const selected = useMemo<MenuFilterEntry | null>(() => {
        // Only a primitive scalar can become a synthetic entry — a stray
        // array/object value would stringify to junk ("[object Object]").
        if (value == null || value === '' || (typeof value !== 'string' && typeof value !== 'number')) {
            return null
        }
        const isDataWarehouse = selectedGroupType === TaxonomicFilterGroupType.DataWarehouse
        const item = {
            id: value,
            name: String(value),
            ...(isDataWarehouse ? dataWarehouseTablesMap[String(value)] : {}),
        }
        return {
            item,
            group: {
                type: selectedGroupType,
                getName: (t: any) => t?.name,
                getValue: (t: any) => t?.name ?? t?.id,
            },
            name: String(value),
        } as unknown as MenuFilterEntry
    }, [value, selectedGroupType, dataWarehouseTablesMap])

    return (
        <TaxonomicFilterHeadless.Root
            // `display: contents` — the Root wrapper div must not affect
            // layout, so the trigger sizes exactly as a bare button would.
            className="contents"
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
            propertyAllowList={propertyAllowList}
            optionsFromProp={optionsFromProp}
            hideBehavioralCohorts={hideBehavioralCohorts}
            endpointFilters={endpointFilters}
            hogQLGlobals={hogQLGlobals}
            showNumericalPropsOnly={showNumericalPropsOnly}
            maxContextOptions={maxContextOptions}
            allowNonCapturedEvents={allowNonCapturedEvents}
            suggestedFiltersLabel={suggestedFiltersLabel}
            enableKeywordShortcuts={enableKeywordShortcuts}
            onChange={(group, changedValue, item) => {
                // Defensive — the orchestrator always resolves a real group
                // on commit, but a missing one would crash consumers that
                // dereference `group.type`.
                if (!group) {
                    return
                }
                onChange(changedValue as ValueType, group.type, item, group)
            }}
        >
            <TaxonomicFilterMenu
                selected={selected}
                dataWarehousePopoverFields={dataWarehousePopoverFields}
                fullWidthTrigger={!!triggerButtonProps?.fullWidth}
                triggerAccessory={<TaxonomicMenuToggle />}
                triggerVariant={triggerVariant}
                // Open immediately — this component is mounted in response
                // to the user's first trigger interaction (see `TaxonomicPopoverMenu`).
                // `defaultOpenState` routes that open to the panel matching the
                // interaction: the search box → combobox, the filter icon → menu.
                defaultOpen
                defaultOpenState={defaultOpenState}
                trigger={({ open }) =>
                    buildTriggerButton({ value, renderValue, placeholder, placeholderClass, triggerButtonProps, open })
                }
            />
        </TaxonomicFilterHeadless.Root>
    )
}
