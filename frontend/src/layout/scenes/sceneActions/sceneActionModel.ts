import type { ReactNode } from 'react'

import type { ActionMenuItem } from '@posthog/quill'

/**
 * The menu an action lives in. Known groups render in canonical order with their canonical label; any other string
 * becomes a menu labeled with that string, after View. Metadata actions sit on the top level of the menu, not in a
 * submenu. Help is reserved: every scene gets it.
 */
export type SceneActionGroup = 'file' | 'edit' | 'view' | 'metadata' | 'staff' | (string & {})

export type ScenePinnedVariant = 'primary' | 'secondary' | 'icon'

export interface ScenePinned {
    /** Orders actions of one variant. The title row shows icons, then secondary actions, then the primary action. */
    order: number
    variant: ScenePinnedVariant
    /** A title control the default button cannot express, such as a status select. The menu still uses the item. */
    render?: () => ReactNode
    /** The title button's `data-attr`, when the scene's title button already had one. Defaults to `${id}-title`. */
    dataAttr?: string
}

/**
 * One action a scene offers. The menu renders every action. An action with `pinned` shows in the title row too, so an
 * action that is in the title row but missing from the menu cannot be expressed.
 *
 * `id` is stable: it doubles as the row's `data-attr` and the captured analytics `item`, so it is a wire string.
 */
export type SceneAction = ActionMenuItem & {
    group: SceneActionGroup
    pinned?: ScenePinned
}

export const MAX_PINNED: Record<ScenePinnedVariant, number> = { primary: 1, secondary: 2, icon: 2 }

const GROUP_LABELS: Record<string, string> = {
    file: 'File',
    edit: 'Edit',
    view: 'View',
    staff: 'Staff only',
    help: 'Help',
}
const LEADING_GROUPS = ['file', 'edit', 'view']
const TRAILING_GROUPS = ['metadata', 'staff', 'help']

export function sceneActionGroupLabel(group: SceneActionGroup): string {
    return GROUP_LABELS[group] ?? group
}

function withDataAttrs(item: ActionMenuItem): ActionMenuItem {
    const dataAttr = item.dataAttr ?? item.id
    return item.type === 'submenu' ? { ...item, dataAttr, items: item.items.map(withDataAttrs) } : { ...item, dataAttr }
}

export function orderedSceneActionGroups(actions: SceneAction[]): SceneActionGroup[] {
    const declared = Array.from(new Set(actions.map((action) => action.group)))
    const custom = declared.filter((group) => !LEADING_GROUPS.includes(group) && !TRAILING_GROUPS.includes(group))
    return [...LEADING_GROUPS, ...custom, ...TRAILING_GROUPS].filter((group) => declared.includes(group))
}

export function stripSceneFields({ group: _group, pinned: _pinned, ...item }: SceneAction): ActionMenuItem {
    return withDataAttrs(item as ActionMenuItem)
}

export function sceneActionMenuDataAttr(
    group: SceneActionGroup,
    dataAttrKey?: string,
    menuDataAttrs?: Partial<Record<SceneActionGroup, string>>
): string | undefined {
    return menuDataAttrs?.[group] ?? (dataAttrKey ? `${dataAttrKey}-menubar-${group}` : undefined)
}

/** The item tree for the "More actions" menu: one top-level submenu per group, metadata rows on the top level itself. */
export function buildSceneActionMenu(
    actions: SceneAction[],
    dataAttrKey?: string,
    menuDataAttrs?: Partial<Record<SceneActionGroup, string>>
): ActionMenuItem[] {
    return orderedSceneActionGroups(actions).flatMap((group): ActionMenuItem[] => {
        const items = actions.filter((action) => action.group === group).map(stripSceneFields)
        if (group === 'metadata') {
            return items.map((item) => ({ ...item, section: 'menus' }))
        }
        return [
            {
                type: 'submenu',
                id: `group:${group}`,
                label: sceneActionGroupLabel(group),
                dataAttr: sceneActionMenuDataAttr(group, dataAttrKey, menuDataAttrs),
                section: 'menus',
                items,
            },
        ]
    })
}

const VARIANT_POSITION: Record<ScenePinnedVariant, number> = { icon: 0, secondary: 1, primary: 2 }

/**
 * The actions the title row shows: icons, then secondary, then the primary action last, each by `order`. Each variant
 * has a cap, and an action over it stays in the menu only, so a scene cannot crowd the title row.
 */
export function pinnedSceneActions(actions: SceneAction[]): (SceneAction & { pinned: ScenePinned })[] {
    const counts: Record<ScenePinnedVariant, number> = { primary: 0, secondary: 0, icon: 0 }
    return actions
        .filter((action): action is SceneAction & { pinned: ScenePinned } => !!action.pinned)
        .sort((a, b) => a.pinned.order - b.pinned.order)
        .filter((action) => {
            const variant = action.pinned.variant
            counts[variant] += 1
            return counts[variant] <= MAX_PINNED[variant]
        })
        .sort((a, b) => VARIANT_POSITION[a.pinned.variant] - VARIANT_POSITION[b.pinned.variant])
}
