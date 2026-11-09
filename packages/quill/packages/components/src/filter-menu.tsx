import { ListFilter } from 'lucide-react'
import * as React from 'react'

import {
    Button,
    cn,
    DropdownMenuCheckboxItem,
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuList,
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
} from '@posthog/quill-primitives'

export interface FilterOption<Value extends string = string> {
    value: Value
    label: string
    icon?: React.ReactNode
    /** A muted note after the label, such as "(you)". */
    hint?: string
}

export interface FilterMenuOpenTiming {
    durationMs: number
    optionCount: number
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

/** The row for "all of them", the empty selection. */
function FilterAllRow({
    label,
    icon,
    checked,
    onSelect,
    dataAttr,
}: {
    label: string
    icon?: React.ReactNode
    checked: boolean
    onSelect: () => void
    dataAttr?: string
}): React.ReactElement {
    return (
        <DropdownMenuCheckboxItem
            label={label}
            checked={checked}
            closeOnClick={false}
            onCheckedChange={onSelect}
            title={label}
            data-attr={dataAttr}
        >
            {icon}
            <span className="truncate">{label}</span>
        </DropdownMenuCheckboxItem>
    )
}

function FilterOptionRows<Value extends string>({
    options,
    selected,
    onChange,
    dataAttr,
}: {
    options: readonly FilterOption<Value>[]
    selected: readonly Value[]
    onChange: (selected: Value[]) => void
    dataAttr?: string
}): React.ReactElement {
    return (
        <>
            {options.map((option) => (
                <DropdownMenuCheckboxItem
                    key={option.value}
                    label={option.label}
                    checked={selected.includes(option.value)}
                    closeOnClick={false}
                    onCheckedChange={(checked) =>
                        onChange(
                            checked ? [...selected, option.value] : selected.filter((value) => value !== option.value)
                        )
                    }
                    title={option.label}
                    data-attr={dataAttr}
                >
                    {option.icon}
                    <span className="truncate">{option.label}</span>
                    {option.hint && <span className="ml-auto text-xs text-muted-foreground">{option.hint}</span>}
                </DropdownMenuCheckboxItem>
            ))}
        </>
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
            <FilterAllRow
                label={allLabel}
                icon={allIcon}
                checked={selected.length === 0}
                onSelect={() => onChange([])}
                dataAttr={optionDataAttr}
            />
            <DropdownMenuSeparator />
            <FilterOptionRows options={options} selected={selected} onChange={onChange} dataAttr={optionDataAttr} />
        </FilterSubMenu>
    )
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
    onOpened,
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
    /** Called once the open submenu has painted, with how long that took and how many options it listed. */
    onOpened?: (timing: FilterMenuOpenTiming) => void
    dataAttr?: string
    optionDataAttr?: string
}): React.ReactElement {
    // Values the options do not know yet, such as a tag from the URL before the list loads, still count as picked.
    const unknown = selected.filter((value) => !options.some((option) => option.value === value))
    const known: FilterOption[] = [...options, ...unknown.map((value) => ({ value, label: value }))]
    const picked = known.filter((option) => selected.includes(option.value))
    const handleOpenChange = (open: boolean): void => {
        if (!open) {
            return
        }
        onOpen?.()
        if (onOpened) {
            const startedAt = performance.now()
            // The first frame runs after the rows have rendered, and the second after they have painted.
            requestAnimationFrame(() =>
                requestAnimationFrame(() =>
                    onOpened({ durationMs: performance.now() - startedAt, optionCount: known.length })
                )
            )
        }
    }
    return (
        <DropdownMenuFilterProvider autoHighlight>
            <DropdownMenuSub onOpenChange={handleOpenChange}>
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
                    {/* Autofocus because Base UI leaves the focus on the row when hover opens the submenu, and typing would go nowhere. */}
                    <DropdownMenuInput autoFocus placeholder={searchPlaceholder} aria-label={searchPlaceholder} />
                    <DropdownMenuEmpty>{emptyText}</DropdownMenuEmpty>
                    <DropdownMenuList>
                        <FilterAllRow
                            label={allLabel}
                            checked={selected.length === 0}
                            onSelect={() => onChange([])}
                            dataAttr={optionDataAttr}
                        />
                        <FilterOptionRows
                            options={known}
                            selected={selected}
                            onChange={onChange}
                            dataAttr={optionDataAttr}
                        />
                    </DropdownMenuList>
                    {loading && <div className="p-2 text-xs text-muted-foreground">Loading…</div>}
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        </DropdownMenuFilterProvider>
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
