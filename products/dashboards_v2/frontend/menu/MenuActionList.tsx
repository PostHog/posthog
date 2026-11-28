import {
    type ContextMenuCheckboxItem,
    type ContextMenuGroup,
    type ContextMenuItem,
    type ContextMenuLabel,
    type ContextMenuRadioGroup,
    type ContextMenuRadioItem,
    type ContextMenuSeparator,
    type ContextMenuSub,
    type ContextMenuSubContent,
    type ContextMenuSubTrigger,
    Spinner,
} from '@posthog/quill'

import { MENU_GROUPS, type MenuAction } from './menuAction'

/** Typed as the right-click parts; quill's dropdown parts take the same props. */
export type MenuParts = {
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
    if (action.loading) {
        return (
            <span className="flex items-center gap-2">
                {action.label}
                <Spinner aria-label={action.disabledReason} />
            </span>
        )
    }
    return (
        <span className="flex flex-col items-start text-left">
            <span>{action.label}</span>
            <span className="text-xs text-muted-foreground">{action.disabledReason}</span>
        </span>
    )
}

// A menu row has a fixed height, and a disabled entry needs a second line for its reason.
function rowClass(action: MenuAction): string | undefined {
    return action.disabledReason && !action.loading ? 'h-auto py-1' : undefined
}

function sectionsOf(actions: MenuAction[]): { label?: string; actions: MenuAction[] }[] {
    const labels = [...new Set(actions.map((action) => action.section))]
    if (labels.length < 2) {
        return [{ actions }]
    }
    return labels.map((label) => ({ label, actions: actions.filter((action) => action.section === label) }))
}

function RadioChoices({ choices, parts }: { choices: MenuAction[]; parts: MenuParts }): JSX.Element {
    const { RadioGroup, RadioItem } = parts
    return (
        <RadioGroup
            value={choices.find((choice) => choice.checked)?.key ?? null}
            onValueChange={(value) => choices.find((choice) => choice.key === value)?.onSelect?.()}
        >
            {choices.map((choice) => (
                <RadioItem
                    key={choice.key}
                    value={choice.key}
                    data-attr={choice.dataAttr}
                    className={rowClass(choice)}
                    disabled={!!choice.disabledReason}
                >
                    <EntryLabel action={choice} />
                </RadioItem>
            ))}
        </RadioGroup>
    )
}

function MenuEntry({ action, parts }: { action: MenuAction; parts: MenuParts }): JSX.Element {
    const { Group, Label, Separator, Item, CheckboxItem, Sub, SubTrigger, SubContent } = parts
    if (action.submenu && action.choice) {
        return (
            <Sub>
                <SubTrigger data-attr={action.dataAttr} className={rowClass(action)} disabled={!!action.disabledReason}>
                    <EntryLabel action={action} />
                </SubTrigger>
                <SubContent>
                    <RadioChoices choices={action.submenu} parts={parts} />
                </SubContent>
            </Sub>
        )
    }
    if (action.submenu) {
        return (
            <Sub>
                <SubTrigger data-attr={action.dataAttr} className={rowClass(action)} disabled={!!action.disabledReason}>
                    <EntryLabel action={action} />
                </SubTrigger>
                <SubContent>
                    {sectionsOf(action.submenu).map((section, index) => (
                        <Group key={section.label ?? index}>
                            {index > 0 && <Separator />}
                            {section.label && <Label>{section.label}</Label>}
                            {section.actions.every((child) => child.exclusive) ? (
                                <RadioChoices choices={section.actions} parts={parts} />
                            ) : (
                                section.actions.map((child) => (
                                    <MenuEntry key={child.key} action={child} parts={parts} />
                                ))
                            )}
                        </Group>
                    ))}
                </SubContent>
            </Sub>
        )
    }
    if (action.checked !== undefined) {
        return (
            <CheckboxItem
                data-attr={action.dataAttr}
                className={rowClass(action)}
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
            className={rowClass(action)}
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
