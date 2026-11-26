import type {
    ContextMenuCheckboxItem,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
} from '@posthog/quill'

import { MENU_GROUPS, type MenuAction } from './menuAction'

/** Typed as the right-click parts; quill's dropdown parts take the same props. */
export interface MenuParts {
    Group: typeof ContextMenuGroup
    Label: typeof ContextMenuLabel
    Separator: typeof ContextMenuSeparator
    Item: typeof ContextMenuItem
    CheckboxItem: typeof ContextMenuCheckboxItem
    Sub: typeof ContextMenuSub
    SubTrigger: typeof ContextMenuSubTrigger
    SubContent: typeof ContextMenuSubContent
    RadioGroup: typeof ContextMenuRadioGroup
    RadioItem: typeof ContextMenuRadioItem
}

/** A disabled entry says why under its label, since a tooltip never shows on a touch screen. */
function EntryLabel({ action }: { action: MenuAction }): JSX.Element {
    if (!action.disabledReason) {
        return <>{action.label}</>
    }
    return (
        <span className="flex flex-col items-start text-left">
            <span>{action.label}</span>
            <span className="text-xs text-muted-foreground">{action.disabledReason}</span>
        </span>
    )
}

function MenuEntry({ action, parts }: { action: MenuAction; parts: MenuParts }): JSX.Element {
    const { Item, CheckboxItem, Sub, SubTrigger, SubContent, RadioGroup, RadioItem } = parts
    if (action.submenu && action.choice) {
        const selected = action.submenu.find((child) => child.checked)?.key ?? null
        return (
            <Sub>
                <SubTrigger data-attr={action.dataAttr} disabled={!!action.disabledReason}>
                    <EntryLabel action={action} />
                </SubTrigger>
                <SubContent>
                    <RadioGroup
                        value={selected}
                        onValueChange={(value) => action.submenu?.find((child) => child.key === value)?.onSelect?.()}
                    >
                        {action.submenu.map((child) => (
                            <RadioItem
                                key={child.key}
                                value={child.key}
                                data-attr={child.dataAttr}
                                disabled={!!child.disabledReason}
                            >
                                <EntryLabel action={child} />
                            </RadioItem>
                        ))}
                    </RadioGroup>
                </SubContent>
            </Sub>
        )
    }
    if (action.submenu) {
        return (
            <Sub>
                <SubTrigger data-attr={action.dataAttr} disabled={!!action.disabledReason}>
                    <EntryLabel action={action} />
                </SubTrigger>
                <SubContent>
                    {action.submenu.map((child) => (
                        <MenuEntry key={child.key} action={child} parts={parts} />
                    ))}
                </SubContent>
            </Sub>
        )
    }
    if (action.checked !== undefined) {
        return (
            <CheckboxItem
                data-attr={action.dataAttr}
                checked={action.checked}
                disabled={!!action.disabledReason}
                onCheckedChange={() => action.onSelect?.()}
            >
                <EntryLabel action={action} />
            </CheckboxItem>
        )
    }
    return (
        <Item
            data-attr={action.dataAttr}
            variant={action.destructive ? 'destructive' : 'default'}
            disabled={!!action.disabledReason}
            closeOnClick={!action.keepOpen}
            onClick={action.onSelect}
        >
            <EntryLabel action={action} />
        </Item>
    )
}

function menuGroups(actions: MenuAction[]): { key: string; label?: string; actions: MenuAction[] }[] {
    const groups = [
        { key: 'actions', label: 'Actions', actions: actions.filter((action) => !action.group && !action.destructive) },
        ...MENU_GROUPS.map(({ group, label }) => ({
            key: group,
            label,
            actions: actions.filter((action) => action.group === group),
        })),
        { key: 'destructive', actions: actions.filter((action) => action.destructive) },
    ]
    return groups.filter((group) => group.actions.length > 0)
}

export function MenuActionList({ actions, parts }: { actions: MenuAction[]; parts: MenuParts }): JSX.Element {
    const { Group, Label, Separator } = parts
    return (
        <>
            {menuGroups(actions).map((group, index) => (
                <Group key={group.key}>
                    {index > 0 && <Separator />}
                    {group.label && <Label>{group.label}</Label>}
                    {group.actions.map((action) => (
                        <MenuEntry key={action.key} action={action} parts={parts} />
                    ))}
                </Group>
            ))}
        </>
    )
}
