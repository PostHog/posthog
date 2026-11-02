import { Fragment, ReactNode } from 'react'

import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from '@posthog/quill'

import {
    LemonMenuItem,
    LemonMenuItemCustom,
    LemonMenuItemNode,
    LemonMenuItems,
    LemonMenuSection,
} from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

type PresentItem = Exclude<LemonMenuItems[number], false | null>
type MenuEntry = Exclude<LemonMenuItem, LemonMenuItemCustom>
type MenuLeaf = Exclude<MenuEntry, LemonMenuItemNode>

function tooltipText(tooltip: MenuEntry['tooltip']): ReactNode {
    return typeof tooltip === 'function' ? tooltip() : tooltip
}

function isSection(item: PresentItem): item is LemonMenuSection {
    return !('label' in item)
}

function isCustom(item: LemonMenuItem): item is LemonMenuItemCustom {
    return typeof item.label === 'function'
}

function isNode(item: MenuEntry): item is LemonMenuItemNode {
    return Array.isArray(item.items)
}

function itemKey(item: LemonMenuItem, index: number): string {
    // Items in one menu often share a data-attr, so the index keeps keys and radio values unique.
    return `${index}-${String(item.key ?? (isCustom(item) ? '' : (item['data-attr'] ?? item.label)))}`
}

/** Renders Lemon menu item definitions as quill dropdown menu content, so the Lemon and quill menus share one list. */
export function QuillMenuItems({
    items,
    closeOnClick = true,
}: {
    items: LemonMenuItems
    closeOnClick?: boolean
}): JSX.Element {
    const sections: LemonMenuSection[] = []
    for (const item of items) {
        if (!item) {
            continue
        }
        if (isSection(item)) {
            sections.push(item)
        } else if (
            sections.length &&
            !sections[sections.length - 1].title &&
            !('key' in sections[sections.length - 1])
        ) {
            sections[sections.length - 1].items.push(item)
        } else {
            sections.push({ items: [item] })
        }
    }

    return (
        <>
            {sections.map((section, index) => (
                <Fragment key={section.key ?? index}>
                    {index > 0 && <DropdownMenuSeparator />}
                    <DropdownMenuGroup>
                        {section.title && <DropdownMenuLabel>{section.title}</DropdownMenuLabel>}
                        <SectionItems
                            items={section.items.filter((item): item is LemonMenuItem => !!item)}
                            closeOnClick={closeOnClick}
                        />
                        {section.footer}
                    </DropdownMenuGroup>
                </Fragment>
            ))}
        </>
    )
}

function SectionItems({ items, closeOnClick }: { items: LemonMenuItem[]; closeOnClick: boolean }): JSX.Element {
    const exclusive = items.some((item) => 'active' in item && item.active !== undefined)
    if (!exclusive) {
        return (
            <>
                {items.map((item, index) => (
                    <Entry key={itemKey(item, index)} item={item} closeOnClick={closeOnClick} />
                ))}
            </>
        )
    }
    const activeIndex = items.findIndex((item) => 'active' in item && item.active)
    return (
        <DropdownMenuRadioGroup value={activeIndex >= 0 ? itemKey(items[activeIndex], activeIndex) : ''}>
            {items.map((item, index) => (
                <Entry
                    key={itemKey(item, index)}
                    item={item}
                    closeOnClick={closeOnClick}
                    radioValue={itemKey(item, index)}
                />
            ))}
        </DropdownMenuRadioGroup>
    )
}

function Entry({
    item,
    closeOnClick,
    radioValue,
}: {
    item: LemonMenuItem
    closeOnClick: boolean
    radioValue?: string
}): JSX.Element {
    if (isCustom(item)) {
        return item.label()
    }
    const entry: MenuEntry = item
    const content = (
        <>
            {entry.icon}
            {entry.label}
            {entry.sideIcon}
        </>
    )
    if (isNode(entry)) {
        return (
            <DropdownMenuSub>
                <DropdownMenuSubTrigger
                    disabled={entry.disabled}
                    disabledReason={entry.disabledReason}
                    tooltip={tooltipText(entry.tooltip)}
                    data-attr={entry['data-attr']}
                >
                    {content}
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                    <QuillMenuItems items={entry.items} closeOnClick={closeOnClick} />
                </DropdownMenuSubContent>
            </DropdownMenuSub>
        )
    }
    const leaf: MenuLeaf = entry
    if (radioValue !== undefined) {
        return (
            <DropdownMenuRadioItem
                value={radioValue}
                onClick={leaf.onClick}
                closeOnClick={closeOnClick}
                disabled={entry.disabled}
                disabledReason={entry.disabledReason}
                tooltip={tooltipText(entry.tooltip)}
                data-attr={entry['data-attr']}
            >
                {content}
            </DropdownMenuRadioItem>
        )
    }
    return (
        <DropdownMenuItem
            onClick={leaf.onClick}
            closeOnClick={closeOnClick}
            variant={leaf.status === 'danger' ? 'destructive' : 'default'}
            disabled={entry.disabled}
            disabledReason={entry.disabledReason}
            tooltip={tooltipText(entry.tooltip)}
            data-attr={entry['data-attr']}
            {...('to' in entry
                ? {
                      render: (
                          <LinkPrimitive
                              to={entry.to}
                              target={entry.targetBlank ? '_blank' : undefined}
                              disableClientSideRouting={entry.disableClientSideRouting}
                          />
                      ),
                  }
                : {})}
        >
            {content}
        </DropdownMenuItem>
    )
}
