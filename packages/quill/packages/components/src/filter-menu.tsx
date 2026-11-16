import { ListFilter } from 'lucide-react'
import * as React from 'react'

import {
    Button,
    cn,
    Combobox,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    DropdownMenuCheckboxItem,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    useComboboxFilteredItems,
} from '@posthog/quill-primitives'

export interface FilterOption<Value extends string = string> {
    value: Value
    label: string
    icon?: React.ReactNode
    /** A muted note after the label, such as "(you)". */
    hint?: string
}

/** What a filter row shows for several values: the default, up to two labels, or a count, such as "3 tags". */
export function filterSummary(labels: string[], allLabel: string, pluralNoun: string): string {
    if (labels.length === 0) {
        return allLabel
    }
    return labels.length > 2 ? `${labels.length} ${pluralNoun}` : labels.join(', ')
}

/** The funnel button that opens a list's filter menu. A dot says a filter narrows the list. */
export function FilterMenuTrigger({ active, dataAttr }: { active: boolean; dataAttr?: string }): React.ReactElement {
    const label = active ? 'Filters on' : 'Filter'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon"
                                aria-label={label}
                                indicator={active ? 'default' : undefined}
                                className={cn('text-muted-foreground', active && 'bg-fill-selected text-foreground')}
                                data-attr={dataAttr}
                            />
                        }
                    />
                }
            >
                <ListFilter />
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    )
}

interface FilterSubMenuRowProps {
    label: string
    /** The choice in force, shown beside the label. */
    value: string
    /** The choice differs from the default, so the value takes the primary color. */
    active?: boolean
    dataAttr?: string
}

function FilterSubMenuRow({ label, value, active = false, dataAttr }: FilterSubMenuRowProps): React.ReactElement {
    return (
        <DropdownMenuSubTrigger data-attr={dataAttr}>
            <span>{label}</span>
            <span
                title={value}
                className={cn('flex-1 truncate pl-4 text-right', active ? 'text-primary' : 'text-muted-foreground')}
            >
                {value}
            </span>
        </DropdownMenuSubTrigger>
    )
}

/** One filter in the menu: its label, the choice in force, and a submenu of the options. */
export function FilterSubMenu({
    children,
    ...row
}: FilterSubMenuRowProps & { children: React.ReactNode }): React.ReactElement {
    return (
        <DropdownMenuSub>
            <FilterSubMenuRow {...row} />
            <DropdownMenuSubContent>{children}</DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

/** A filter with one choice. Leave out `defaultValue` for a row that never counts as a filter, such as a sort. */
export function FilterRadioSubMenu<Value extends string>({
    label,
    options,
    value,
    defaultValue,
    onChange,
    dataAttr,
    optionDataAttr,
}: {
    label: string
    options: readonly FilterOption<Value>[]
    value: Value
    defaultValue?: Value
    onChange: (value: Value) => void
    dataAttr?: string
    optionDataAttr?: string
}): React.ReactElement {
    return (
        <FilterSubMenu
            label={label}
            value={options.find((option) => option.value === value)?.label ?? ''}
            active={defaultValue !== undefined && value !== defaultValue}
            dataAttr={dataAttr}
        >
            <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as Value)}>
                {options.map((option) => (
                    <DropdownMenuRadioItem key={option.value} value={option.value} data-attr={optionDataAttr}>
                        {option.icon}
                        {option.label}
                    </DropdownMenuRadioItem>
                ))}
            </DropdownMenuRadioGroup>
        </FilterSubMenu>
    )
}

/** A filter with several choices from a short list. An empty selection means all of them. */
export function FilterCheckboxSubMenu<Value extends string>({
    label,
    allLabel,
    allIcon,
    pluralNoun,
    options,
    selected,
    onChange,
    dataAttr,
    optionDataAttr,
}: {
    label: string
    allLabel: string
    allIcon?: React.ReactNode
    pluralNoun: string
    options: readonly FilterOption<Value>[]
    selected: readonly Value[]
    onChange: (selected: Value[]) => void
    dataAttr?: string
    optionDataAttr?: string
}): React.ReactElement {
    const labels = options.filter((option) => selected.includes(option.value)).map((option) => option.label)
    return (
        <FilterSubMenu
            label={label}
            value={filterSummary(labels, allLabel, pluralNoun)}
            active={selected.length > 0}
            dataAttr={dataAttr}
        >
            <DropdownMenuCheckboxItem
                checked={selected.length === 0}
                closeOnClick={false}
                onCheckedChange={() => onChange([])}
                data-attr={optionDataAttr}
            >
                {allIcon}
                {allLabel}
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            {options.map((option) => (
                <DropdownMenuCheckboxItem
                    key={option.value}
                    checked={selected.includes(option.value)}
                    closeOnClick={false}
                    onCheckedChange={(checked) =>
                        onChange(
                            checked ? [...selected, option.value] : selected.filter((value) => value !== option.value)
                        )
                    }
                    data-attr={optionDataAttr}
                >
                    {option.icon}
                    {option.label}
                </DropdownMenuCheckboxItem>
            ))}
        </FilterSubMenu>
    )
}

// The search field and rows sit in the menu's popup, whose own key and click handling would close the menu or steal them.
const stopPropagation = (event: React.SyntheticEvent): void => event.stopPropagation()

type SearchOption = FilterOption<string> | { value: null; label: string; icon?: undefined; hint?: undefined }

// Each row is a mounted component, and opening the menu slows past a few hundred of them.
const SEARCH_OPTION_LIMIT = 200

function SearchLimitHint(): React.ReactElement | null {
    const reachedLimit = useComboboxFilteredItems().length >= SEARCH_OPTION_LIMIT
    return reachedLimit ? <div className="p-2 text-xs text-muted-foreground">Keep typing to see more</div> : null
}

/** A filter with several choices from a long list, such as people or tags. An empty selection means all of them. */
export function FilterSearchSubMenu({
    label,
    allLabel,
    pluralNoun,
    options,
    selected,
    onChange,
    loading,
    searchPlaceholder,
    emptyText,
    onOpen,
    dataAttr,
    optionDataAttr,
}: {
    label: string
    allLabel: string
    pluralNoun: string
    options: readonly FilterOption[]
    selected: readonly string[]
    onChange: (selected: string[]) => void
    loading?: boolean
    searchPlaceholder: string
    emptyText: string
    /** Called when the submenu opens, to load its options only once someone wants them. */
    onOpen?: () => void
    dataAttr?: string
    optionDataAttr?: string
}): React.ReactElement {
    const allOption: SearchOption = { value: null, label: allLabel }
    // Values the options do not know yet, such as a tag from the URL before the list loads, still count as picked.
    const unknown = selected.filter((value) => !options.some((option) => option.value === value))
    const known: FilterOption[] = [...options, ...unknown.map((value) => ({ value, label: value }))]
    const picked = known.filter((option) => selected.includes(option.value))
    return (
        <DropdownMenuSub onOpenChange={(open) => open && onOpen?.()}>
            <FilterSubMenuRow
                label={label}
                value={filterSummary(
                    picked.map((option) => option.label),
                    allLabel,
                    pluralNoun
                )}
                active={selected.length > 0}
                dataAttr={dataAttr}
            />
            {/* Flush because the list scrolls on its own, under a search field that stays put. */}
            <DropdownMenuSubContent flush className="w-64">
                <Combobox<SearchOption, true>
                    multiple
                    // The submenu is the popup, so the list is always open and a pick resets the search.
                    inline
                    autoHighlight
                    limit={SEARCH_OPTION_LIMIT}
                    items={[allOption, ...known]}
                    itemToStringValue={(option) => option.label}
                    isItemEqualToValue={(option, other) => option.value === other.value}
                    value={picked.length > 0 ? picked : [allOption]}
                    onValueChange={(next, { reason }) => {
                        // The list counts as closed while inline, so Base UI treats Escape as a request to clear.
                        if (reason === 'escape-key') {
                            return
                        }
                        // While nothing is picked, "all" is the ticked row, so ticking a value also carries it along.
                        const allTicked = next.some((option) => option.value === null)
                        onChange(
                            allTicked && selected.length > 0
                                ? []
                                : next.flatMap((option) => (option.value === null ? [] : [option.value]))
                        )
                    }}
                >
                    <div className="p-1">
                        <ComboboxInput
                            autoFocus
                            showTrigger={false}
                            placeholder={searchPlaceholder}
                            aria-label={searchPlaceholder}
                            data-compact=""
                            onClick={stopPropagation}
                            onKeyDown={(event) => {
                                if (event.key !== 'Escape') {
                                    event.stopPropagation()
                                }
                            }}
                        />
                    </div>
                    <ComboboxEmpty>{emptyText}</ComboboxEmpty>
                    <ComboboxList>
                        {(option: SearchOption) => (
                            <ComboboxItem
                                key={option.value ?? 'all'}
                                value={option}
                                title={option.label}
                                onClick={stopPropagation}
                                data-attr={optionDataAttr}
                            >
                                {option.icon}
                                <span className="truncate">{option.label}</span>
                                {option.hint && (
                                    <span className="ml-auto text-xs text-muted-foreground">{option.hint}</span>
                                )}
                            </ComboboxItem>
                        )}
                    </ComboboxList>
                    <SearchLimitHint />
                    {loading && <div className="p-2 text-xs text-muted-foreground">Loading…</div>}
                </Combobox>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

/** The last row of the menu, after a separator. It only shows while a filter is on. */
export function FilterClearItem({
    active,
    onClear,
    dataAttr,
}: {
    active: boolean
    onClear: () => void
    dataAttr?: string
}): React.ReactElement | null {
    if (!active) {
        return null
    }
    return (
        <>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onClear} data-attr={dataAttr}>
                Clear filters
            </DropdownMenuItem>
        </>
    )
}
