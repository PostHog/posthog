import { Fragment } from 'react'

import type { ActionMenuItem, ActionMenuPanel } from '@posthog/quill'

import {
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarPopover,
    SceneMenuBarRadioGroup,
    SceneMenuBarRadioItem,
    SceneMenuBarSeparator,
    SceneMenuBarShortcut,
    SceneMenuBarSubMenu,
} from '../components/SceneMenuBar'
import {
    SceneAction,
    SceneActionGroup,
    orderedSceneActionGroups,
    sceneActionGroupLabel,
    sceneActionMenuDataAttr,
} from './sceneActionModel'

function LegacyItem({ item }: { item: ActionMenuItem }): JSX.Element | null {
    const dataAttr = item.dataAttr ?? item.id
    switch (item.type) {
        case 'submenu':
            return (
                <SceneMenuBarSubMenu
                    label={
                        item.icon ? (
                            <>
                                {item.icon}
                                {item.label}
                            </>
                        ) : (
                            item.label
                        )
                    }
                    withIconBlank={!item.icon}
                    keepAsSubmenu={item.display === 'submenu' || item.searchable === false}
                    onOpenChange={item.onOpenChange}
                >
                    <LegacyItems items={item.items} />
                </SceneMenuBarSubMenu>
            )
        case 'checkbox':
            return (
                <SceneMenuBarCheckboxItem
                    checked={item.checked}
                    onCheckedChange={(checked) => item.onCheckedChange(checked)}
                    disabled={!!item.disabledReason}
                    data-attr={dataAttr}
                >
                    {item.label}
                </SceneMenuBarCheckboxItem>
            )
        case 'radio':
            // The menu bar shows a choice as a submenu named after it, as macOS does.
            return (
                <SceneMenuBarSubMenu label={item.label}>
                    <SceneMenuBarRadioGroup value={item.value} onValueChange={(value) => item.onValueChange(value)}>
                        {item.options.map((option) => (
                            <SceneMenuBarRadioItem
                                key={option.value}
                                value={option.value}
                                disabled={!!option.disabledReason}
                                data-attr={`${dataAttr}-${option.value}`}
                            >
                                {option.icon}
                                {option.label}
                            </SceneMenuBarRadioItem>
                        ))}
                    </SceneMenuBarRadioGroup>
                </SceneMenuBarSubMenu>
            )
        case 'panel':
            // The menu bar has no nested popovers. Top-level panels render as their own popover menus.
            return null
        default:
            return (
                <SceneMenuBarItem
                    variant={item.destructive ? 'destructive' : undefined}
                    disabled={!!item.disabledReason}
                    tooltip={item.disabledReason ?? item.tooltip}
                    opensFloatingUi={item.opensFloatingUi && !item.destructive}
                    onClick={() => item.onSelect()}
                    data-attr={dataAttr}
                >
                    {item.icon}
                    {item.label}
                    {item.shortcut && <SceneMenuBarShortcut>{item.shortcut}</SceneMenuBarShortcut>}
                </SceneMenuBarItem>
            )
    }
}

function LegacyItems({ items }: { items: ActionMenuItem[] }): JSX.Element {
    return (
        <>
            {items.map((item, index) => (
                <Fragment key={item.id}>
                    {index > 0 && item.section !== items[index - 1].section && <SceneMenuBarSeparator />}
                    <LegacyItem item={item} />
                </Fragment>
            ))}
        </>
    )
}

function nestedPanels(items: ActionMenuItem[]): ActionMenuPanel[] {
    return items.flatMap((item) =>
        item.type === 'panel' ? [item] : item.type === 'submenu' ? nestedPanels(item.items) : []
    )
}

function LegacyPanel({ panel }: { panel: ActionMenuPanel }): JSX.Element {
    return (
        <SceneMenuBarPopover
            label={panel.label}
            dataAttr={panel.dataAttr ?? panel.id}
            contentClassName={panel.panelClassName ?? 'flex flex-col gap-2'}
        >
            {panel.render()}
        </SceneMenuBarPopover>
    )
}

/**
 * Renders scene actions through the menu bar primitives, for every scene with the `scene-actions` flag off. Those
 * primitives then draw the legacy menu bar, or the "More actions" menu of the Today layout, exactly as before.
 */
export function SceneActionsLegacyMenus({
    actions,
    dataAttrKey,
    menuDataAttrs,
}: {
    actions: SceneAction[]
    dataAttrKey?: string
    menuDataAttrs?: Partial<Record<SceneActionGroup, string>>
}): JSX.Element {
    const groups = orderedSceneActionGroups(actions).filter((group) => group !== 'help')
    return (
        <>
            {groups.map((group) => {
                const items = actions.filter((action) => action.group === group)
                const rows = items.filter((item) => item.type !== 'panel')
                return (
                    <Fragment key={group}>
                        {rows.length > 0 && (
                            <SceneMenuBarMenu
                                label={sceneActionGroupLabel(group)}
                                dataAttr={sceneActionMenuDataAttr(group, dataAttrKey, menuDataAttrs)}
                            >
                                <LegacyItems items={rows} />
                            </SceneMenuBarMenu>
                        )}
                        {nestedPanels(items).map((panel) => (
                            <LegacyPanel key={panel.id} panel={panel} />
                        ))}
                    </Fragment>
                )
            })}
        </>
    )
}
