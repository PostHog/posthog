import { useValues } from 'kea'
import { useRef } from 'react'

import { IconSearch } from '@posthog/icons'
import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxSeparator,
    ComboboxTrigger,
    InputGroupAddon,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'

import { TodayPopupResizeHandle } from './TodayPopupResizeHandle'

export interface TodaySwitcherRow {
    /** Unique across every group and action of the menu. */
    value: string
    label: string
    leading?: React.ReactNode
    trailing?: React.ReactNode
    /** A muted second line under the label. */
    description?: React.ReactNode
    dataAttr: string
    /** Disables the row and says why. */
    disabledReason?: string | null
    onSelect: () => void
}

export interface TodaySwitcherGroup {
    label: string
    rows: TodaySwitcherRow[]
}

export interface TodaySwitcherMenuProps {
    /** The trigger button, with its content. */
    trigger: React.ReactElement
    /** A tooltip on the trigger, for an icon-only one. */
    triggerTooltip?: string
    open: boolean
    onOpenChange: (open: boolean) => void
    searchValue: string
    onSearchChange: (value: string) => void
    searchPlaceholder: string
    /** Shown in place of the groups when the search matches none of their rows. */
    noMatchLabel: string
    /** Already filtered by the caller's logic: the menu does not filter. */
    groups: TodaySwitcherGroup[]
    /** The rows after the groups. A search never hides them. */
    actions: TodaySwitcherRow[]
    selectedValue: string | null
    /** The width the menu opens at, and goes back to when the user double-clicks its resize handle. */
    defaultWidth: number
    /** Keeps the width the user dragged the menu to. */
    resizeKey: string
}

/** A group of the list. The actions group has no label: a separator, or the no-match line, heads it instead. */
interface ListGroup {
    value: string | null
    items: string[]
}

const MIN_WIDTH = 200
const MAX_WIDTH = 560

/**
 * A switcher in the top bar: a search field, groups of rows to pick from, and actions at the end. The actions are
 * list items, so the arrow keys and Enter reach them (design.md, section 8). The user can drag the right edge.
 */
export function TodaySwitcherMenu({
    trigger,
    triggerTooltip,
    open,
    onOpenChange,
    searchValue,
    onSearchChange,
    searchPlaceholder,
    noMatchLabel,
    groups,
    actions,
    selectedValue,
    defaultWidth,
    resizeKey,
}: TodaySwitcherMenuProps): JSX.Element {
    const triggerRef = useRef<HTMLButtonElement>(null)
    const popupRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: resizeKey,
        persistent: true,
        placement: 'right',
        containerRef: popupRef,
        minSize: MIN_WIDTH,
        maxSize: MAX_WIDTH,
    }
    const { desiredSize } = useValues(resizerLogic(resizerProps))

    const shownGroups = groups.filter((group) => group.rows.length > 0)
    const listGroups: ListGroup[] = [
        ...shownGroups.map((group) => ({ value: group.label, items: group.rows.map((row) => row.value) })),
        ...(actions.length > 0 ? [{ value: null, items: actions.map((action) => action.value) }] : []),
    ]
    const rowByValue = new Map([...shownGroups.flatMap((group) => group.rows), ...actions].map((r) => [r.value, r]))

    const combobox = (
        <Combobox
            items={listGroups}
            // The caller's logic filters the groups, and the actions always stay.
            filter={null}
            value={selectedValue}
            inputValue={searchValue}
            open={open}
            autoHighlight
            highlightItemOnHover
            itemToStringLabel={(value: string | null) => (value ? (rowByValue.get(value)?.label ?? '') : '')}
            onInputValueChange={(value: string) => onSearchChange(value)}
            onOpenChange={(next: boolean) => onOpenChange(next)}
            onValueChange={(value: string | null) => {
                if (value !== null && value !== selectedValue) {
                    rowByValue.get(value)?.onSelect()
                }
            }}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={triggerTooltip ? <TooltipTrigger delay={0} render={trigger} /> : trigger}
            />
            <ComboboxContent
                ref={popupRef}
                anchor={triggerRef}
                align="start"
                className="[&_[data-slot=combobox-input-group-wrapper]]:border-b-0"
                // quill caps the popup at 24rem, so the cap moves out to the widest the user can drag it.
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    width: desiredSize ?? defaultWidth,
                    maxWidth: `min(${MAX_WIDTH}px, var(--available-width))`,
                }}
                popupSibling={<TodayPopupResizeHandle resizerProps={resizerProps} />}
            >
                <ComboboxInput placeholder={searchPlaceholder} autoFocus showTrigger={false} className="h-7">
                    <InputGroupAddon align="inline-start">
                        <IconSearch className="size-3" />
                    </InputGroupAddon>
                </ComboboxInput>
                <ComboboxList>
                    {(group: ListGroup) => (
                        <ComboboxGroup key={group.value ?? 'actions'} items={group.items}>
                            {group.value !== null ? (
                                <ComboboxLabel>{group.value}</ComboboxLabel>
                            ) : shownGroups.length > 0 ? (
                                <ComboboxSeparator />
                            ) : (
                                <ComboboxLabel>{noMatchLabel}</ComboboxLabel>
                            )}
                            <ComboboxCollection>
                                {(value: string) => {
                                    const row = rowByValue.get(value)!
                                    return (
                                        <ComboboxItem
                                            key={value}
                                            value={value}
                                            action={group.value === null}
                                            disabledReason={row.disabledReason}
                                            description={row.description}
                                            data-attr={row.dataAttr}
                                        >
                                            {row.leading}
                                            <span className="min-w-0 truncate">{row.label}</span>
                                            {row.trailing}
                                        </ComboboxItem>
                                    )
                                }}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )

    if (!triggerTooltip) {
        return combobox
    }
    return (
        <Tooltip>
            {combobox}
            <TooltipContent side="bottom">{triggerTooltip}</TooltipContent>
        </Tooltip>
    )
}
