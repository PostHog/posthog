import { Button, ItemContent, ItemMedia, ItemMenuItem, ItemTitle, MenuLabel, Text } from '@posthog/quill'

import { LemonMenuItem, LemonMenuItems, LemonMenuSection } from 'lib/lemon-ui/LemonMenu'

function isSection(item: LemonMenuItem | LemonMenuSection): item is LemonMenuSection {
    return 'title' in item
}

function itemLabel(item: LemonMenuItem): React.ReactNode {
    return typeof item.label === 'function' ? item.label() : item.label
}

function itemKey(item: LemonMenuItem, index: number): React.Key {
    return item.key ?? (typeof item.label === 'string' ? item.label : index)
}

function MappingMenuRow({ item }: { item: LemonMenuItem }): JSX.Element {
    const icon = 'icon' in item ? item.icon : null
    const disabledReason = 'disabledReason' in item ? item.disabledReason : null

    if (item.items) {
        return (
            <>
                <Text size="xs" variant="muted" render={<div className="flex items-center gap-2 px-2 py-1" />}>
                    {icon}
                    {itemLabel(item)}
                </Text>
                {item.items.map((child, index) =>
                    child ? <MappingMenuRow key={itemKey(child, index)} item={child} /> : null
                )}
            </>
        )
    }

    if (disabledReason) {
        return (
            <Button size="row" left role="menuitem" disabledReason={disabledReason}>
                {icon}
                {itemLabel(item)}
            </Button>
        )
    }

    return (
        <ItemMenuItem
            size="xs"
            className={'status' in item && item.status === 'danger' ? 'text-destructive-foreground' : undefined}
            onClick={'onClick' in item ? item.onClick : undefined}
        >
            {icon && <ItemMedia variant="icon">{icon}</ItemMedia>}
            <ItemContent variant="menuItem">
                <ItemTitle>{itemLabel(item)}</ItemTitle>
            </ItemContent>
        </ItemMenuItem>
    )
}

// Rendered inline, with the submenu flattened: the host is a popover owned by the table, and a portaled
// submenu would count as a click outside it and close it before the row's action ran.
export function QuillCampaignMappingMenu({ items }: { items: LemonMenuItems }): JSX.Element {
    return (
        <div data-quill role="menu" className="flex min-w-48 flex-col gap-px">
            {items.map((item, index) => {
                if (!item) {
                    return null
                }
                if (!isSection(item)) {
                    return <MappingMenuRow key={itemKey(item, index)} item={item} />
                }
                return (
                    <div key={item.key ?? index} role="group" className="flex flex-col gap-px">
                        {item.title && <MenuLabel>{item.title}</MenuLabel>}
                        {item.items.map((child, childIndex) =>
                            child ? <MappingMenuRow key={itemKey(child, childIndex)} item={child} /> : null
                        )}
                    </div>
                )
            })}
        </div>
    )
}
