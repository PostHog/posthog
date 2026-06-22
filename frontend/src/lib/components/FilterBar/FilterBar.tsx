import { useActions, useValues } from 'kea'
import { memo, ReactNode, useMemo, useState } from 'react'

import { IconArrowRight, IconCalendar, IconFilter, IconRefresh, IconSort } from '@posthog/icons'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { UniversalFiltersGroup } from '~/types'

import { DateFilter } from '../DateFilter/DateFilter'
import {
    FilterPicker,
    FilterPickerNode,
    FilterPickerPath,
    FilterPickerToken,
    FilterPickerTokenPill,
} from '../FilterPicker'
import { ExcludedProperties, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { UniversalFilterButton } from '../UniversalFilters/UniversalFilterButton'
import UniversalFilters from '../UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from '../UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from '../UniversalFilters/utils'
import { FilterMenuRoot, MenuNode, TaxonomicMenuFilter } from './FilterMenu'

export type SortDirection = 'ASC' | 'DESC'

export interface FilterBarSortOption {
    value: string
    label: string
}

export interface FilterBarToken {
    key: string
    label: ReactNode
    parts?: ReactNode[]
    title?: string
    onRemove?: () => void
    onClick?: () => void
}

export interface FilterBarNodeRoot {
    kind: 'node'
    node: MenuNode
    token?: FilterBarToken | null
}

export type FilterBarRoot = FilterMenuRoot | FilterBarNodeRoot

export interface FilterBarDateConfig {
    dateFrom?: string | null
    dateTo?: string | null
    onDateChange: (dateFrom: string | null, dateTo: string | null) => void
}

export interface FilterBarReloadConfig {
    onReload: () => void
    loading?: boolean
    disabled?: boolean
}

export interface FilterBarSortConfig {
    options: FilterBarSortOption[]
    value?: string
    direction?: SortDirection
    onChange: (value: string, direction: SortDirection) => void
}

export interface FilterBarProps {
    pickerRootNodes?: FilterPickerNode[]
    pickerTokens?: FilterPickerToken[]
    pickerPlaceholder?: string
    dateConfig?: FilterBarDateConfig
    sortConfig?: FilterBarSortConfig
    reloadConfig?: FilterBarReloadConfig
    disabledReason?: string
    loading?: boolean

    /**
     * Legacy compatibility wiring for Web analytics, marketing analytics, endpoints,
     * customer analytics, and revenue analytics.
     */
    rootKey?: string
    filterGroup?: UniversalFiltersGroup
    onFilterChange?: (group: UniversalFiltersGroup) => void
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    roots?: FilterBarRoot[]
    excludedProperties?: ExcludedProperties
    includeTaxonomicCategories?: boolean

    /** Legacy toolbar props. Prefer dateConfig/sortConfig/reloadConfig. */
    onReload?: () => void
    reloadLoading?: boolean
    dateFrom?: string | null
    dateTo?: string | null
    onDateChange?: (dateFrom: string | null, dateTo: string | null) => void
    sortOptions?: FilterBarSortOption[]
    sortValue?: string
    sortDirection?: SortDirection
    onSortChange?: (value: string, direction: SortDirection) => void
    tokens?: FilterBarToken[]

    className?: string
}

const ISLAND =
    'flex items-center shrink-0 overflow-hidden rounded-lg border bg-[var(--color-bg-fill-input)] shadow-sm [&_.button-primitive]:!rounded-none'

const GroupDivider = (): JSX.Element => <div className="w-px self-stretch bg-border" />

export function FilterBar(props: FilterBarProps): JSX.Element {
    const { rootKey, filterGroup, onFilterChange, taxonomicGroupTypes } = props

    if (rootKey && filterGroup && onFilterChange && taxonomicGroupTypes) {
        return (
            <UniversalFilters
                rootKey={rootKey}
                group={filterGroup}
                taxonomicGroupTypes={taxonomicGroupTypes}
                onChange={onFilterChange}
            >
                <BarContents {...props} />
            </UniversalFilters>
        )
    }

    return <BarContents {...props} />
}

// Legacy compatibility bridge: adapts the older FilterMenu `MenuNode` tree into the generic
// `FilterPickerNode` tree for Web/marketing/customer/revenue analytics and endpoints. Remove once those
// consumers move to the generic picker API directly (see TASKS.md Batch 8 decision).
function menuNodeToPickerNode(node: MenuNode): FilterPickerNode {
    const shared = {
        id: node.id,
        label: node.label,
        tokenLabel: node.pillLabel,
        hint: node.hint,
        section: node.section ? { id: node.section, label: node.section, icon: node.sectionIcon } : undefined,
        searchPlaceholder: node.searchPlaceholder,
    }

    if (node.renderPanel) {
        return { ...shared, kind: 'panel', renderPanel: ({ close }) => node.renderPanel?.({ close }) }
    }

    if (node.useChildren) {
        return {
            ...shared,
            kind: 'branch',
            getChildren: ({ query }) => {
                const result = node.useChildren?.(query) ?? { nodes: [], isLoading: false }
                return { ...result, nodes: result.nodes.map(menuNodeToPickerNode) }
            },
        }
    }

    return { ...shared, kind: 'action', onSelect: ({ close }) => node.onSelect?.({ close }) }
}

// Legacy compatibility bridge: adapts the older `FilterBarToken` into the generic `FilterPickerToken`.
function legacyTokenToPickerToken(token: FilterBarToken, editPath?: FilterPickerPath): FilterPickerToken {
    return {
        id: token.key,
        title: token.title ?? (typeof token.label === 'string' ? token.label : undefined),
        editPath,
        removable: !!token.onRemove,
        editable: !!editPath || !!token.onClick,
        onRemove: token.onRemove,
        parts: token.parts?.length
            ? token.parts.map((part, index) => ({ key: String(index), kind: 'text', label: part }))
            : [{ key: 'label', kind: 'text', label: token.label }],
    }
}

function BarContents({
    pickerRootNodes,
    pickerTokens,
    pickerPlaceholder = 'Filter by property...',
    dateConfig,
    sortConfig,
    reloadConfig,
    disabledReason,
    loading,
    taxonomicGroupTypes = [],
    roots,
    excludedProperties,
    includeTaxonomicCategories,
    onReload,
    reloadLoading,
    dateFrom,
    dateTo,
    onDateChange,
    sortOptions,
    sortValue,
    sortDirection = 'DESC',
    onSortChange,
    tokens,
    className,
}: FilterBarProps): JSX.Element {
    const rootNodes = useMemo<FilterPickerNode[]>(
        () =>
            pickerRootNodes ??
            roots?.flatMap((root) => ('node' in root ? [menuNodeToPickerNode(root.node)] : [])) ??
            [],
        [pickerRootNodes, roots]
    )
    const displayedTokens = useMemo<FilterPickerToken[]>(() => {
        if (pickerTokens) {
            return pickerTokens
        }
        const rootTokens =
            roots?.flatMap((root) =>
                'token' in root && root.token
                    ? [legacyTokenToPickerToken(root.token, 'node' in root ? { nodeIds: [root.node.id] } : undefined)]
                    : []
            ) ?? []
        return [...rootTokens, ...(tokens?.map((token) => legacyTokenToPickerToken(token)) ?? [])]
    }, [pickerTokens, roots, tokens])

    const activeDate = dateConfig ?? (onDateChange ? { dateFrom, dateTo, onDateChange } : undefined)
    const activeSort =
        sortConfig ??
        (onSortChange && sortOptions?.length
            ? { options: sortOptions, value: sortValue, direction: sortDirection, onChange: onSortChange }
            : undefined)
    const activeReload = reloadConfig ?? (onReload ? { onReload, loading: reloadLoading } : undefined)
    const showLeftIsland = !!activeReload || !!activeDate
    const showGenericPicker = !!pickerRootNodes?.length
    const showLegacyTaxonomicPicker = !pickerRootNodes && taxonomicGroupTypes.length > 0

    return (
        <div className={cn('flex items-center gap-2', className)}>
            {showLeftIsland && (
                <div className={ISLAND}>
                    {activeReload && (
                        <ButtonPrimitive
                            iconOnly
                            size="sm"
                            onClick={activeReload.onReload}
                            disabled={activeReload.loading || activeReload.disabled || !!disabledReason || loading}
                            tooltip={disabledReason ?? 'Reload'}
                            aria-label="Reload"
                        >
                            {activeReload.loading ? <Spinner /> : <IconRefresh />}
                        </ButtonPrimitive>
                    )}
                    {activeReload && activeDate && <GroupDivider />}
                    {activeDate && (
                        <DateFilter
                            dateFrom={activeDate.dateFrom}
                            dateTo={activeDate.dateTo}
                            onChange={(from, to) => activeDate.onDateChange(from, to)}
                            renderTrigger={({ ref, label, onClick, isOpen, disabledReason: dateDisabled, tooltip }) => (
                                <ButtonPrimitive
                                    ref={ref}
                                    size="sm"
                                    active={isOpen}
                                    onClick={onClick}
                                    disabled={!!dateDisabled || !!disabledReason || loading}
                                    tooltip={disabledReason ?? dateDisabled ?? tooltip}
                                >
                                    <IconCalendar />
                                    {label}
                                </ButtonPrimitive>
                            )}
                        />
                    )}
                </div>
            )}

            {activeSort && (
                <div className={ISLAND}>
                    <SortControl
                        options={activeSort.options}
                        value={activeSort.value}
                        direction={activeSort.direction ?? 'DESC'}
                        onChange={activeSort.onChange}
                    />
                </div>
            )}

            {showGenericPicker && (
                <div className={cn(ISLAND, 'mr-1')}>
                    <FilterPicker
                        rootNodes={rootNodes}
                        rootSearchPlaceholder={pickerPlaceholder}
                        trigger={
                            <ButtonPrimitive size="sm" disabled={!!disabledReason || loading} tooltip={disabledReason}>
                                <IconFilter />
                                Filter
                            </ButtonPrimitive>
                        }
                    />
                </div>
            )}

            {showLegacyTaxonomicPicker && (
                <div className={cn(ISLAND, 'mr-1')}>
                    <TaxonomicMenuFilter
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        roots={roots}
                        excludedProperties={excludedProperties}
                        includeTaxonomicCategories={includeTaxonomicCategories}
                    />
                </div>
            )}

            <FilterBarTokens tokens={displayedTokens} rootNodes={rootNodes} />
            {showLegacyTaxonomicPicker && <FilterChips />}
        </div>
    )
}

const FilterBarTokens = memo(function FilterBarTokens({
    tokens,
    rootNodes,
}: {
    tokens: FilterPickerToken[]
    rootNodes: FilterPickerNode[]
}): JSX.Element | null {
    if (!tokens.length) {
        return null
    }

    return (
        <div className="flex min-w-0 items-center flex-wrap gap-1">
            {tokens.map((token) => (
                <FilterBarToken key={token.id} token={token} rootNodes={rootNodes} />
            ))}
        </div>
    )
})

const FilterBarToken = memo(function FilterBarToken({
    token,
    rootNodes,
}: {
    token: FilterPickerToken
    rootNodes: FilterPickerNode[]
}): JSX.Element {
    const [open, setOpen] = useState(false)

    if (!token.editPath || token.editable === false || !rootNodes.length) {
        return <FilterPickerTokenPill token={token} onRemove={token.onRemove} className="max-w-64" />
    }

    return (
        <FilterPicker
            rootNodes={rootNodes}
            initialPath={token.editPath}
            open={open}
            onOpenChange={setOpen}
            trigger={
                <FilterPickerTokenPill
                    token={token}
                    onEdit={() => setOpen(true)}
                    onRemove={token.onRemove}
                    className="max-w-64"
                />
            }
        />
    )
})

const DirectionArrow = ({ direction }: { direction: SortDirection }): JSX.Element => (
    <IconArrowRight className={cn(direction === 'DESC' ? 'rotate-90' : '-rotate-90')} />
)

function SortControl({
    options,
    value,
    direction,
    onChange,
}: {
    options: FilterBarSortOption[]
    value?: string
    direction: SortDirection
    onChange: (value: string, direction: SortDirection) => void
}): JSX.Element {
    const activeValue = value ?? options[0]?.value
    const activeLabel = options.find((option) => option.value === activeValue)?.label ?? 'Sort'

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <ButtonPrimitive size="sm" tooltip="Sort">
                        <IconSort />
                        {activeLabel}
                    </ButtonPrimitive>
                }
            />
            <DropdownMenuContent align="start" className="min-w-[210px]">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Sort by</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={activeValue}
                        onValueChange={(next: string) => onChange(next, direction)}
                    >
                        {options.map((option) => (
                            <DropdownMenuRadioItem key={option.value} value={option.value}>
                                {option.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => onChange(activeValue, direction === 'DESC' ? 'ASC' : 'DESC')}>
                    <DirectionArrow direction={direction} />
                    {direction === 'DESC' ? 'Descending' : 'Ascending'}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function FilterChips(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="flex flex-1 min-w-0 items-center flex-wrap gap-1">
            {filterGroup.values.map((filterOrGroup, index) =>
                isUniversalGroupFilterLike(filterOrGroup) ? null : (
                    <UniversalFilterButton key={index} filter={filterOrGroup} onClose={() => removeGroupValue(index)} />
                )
            )}
        </div>
    )
}
