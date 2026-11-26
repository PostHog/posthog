import type { ComponentType } from 'react'
import { z } from 'zod'

import type { MenuAction } from '../../menu/menuAction'
import type { PanelMenuContext } from '../core/panelDefinition'
import type { PanelSize, PanelSpec, TileCustomization } from '../core/panelSpec'

export const CUSTOM_PANEL_SIZE: PanelSize = { w: 12, h: 8, minW: 3, minH: 3 }

export type CustomConfig = { content: string }

export type CustomContent = {
    Component: ComponentType
    Loading?: ComponentType
    size?: PanelSize
    showOnInteractiveOnly?: boolean
    /** Lets a person drag, resize, move and remove the tile. Left out, the tile stays where the host put it. */
    movable?: boolean
    /** Gets the tile's built-in actions and returns the ones to show. Left out, the tile's menu has none of them. */
    menuActions?: (actions: MenuAction[], context: PanelMenuContext<CustomConfig>) => MenuAction[]
}

/** One team's contents, kept in that team's own folder. Documents name each as `<namespace>/<name>`. */
export type ContentPackage = { namespace: string; contents: Record<string, CustomContent> }

export function defineContentPackage(namespace: string, contents: Record<string, CustomContent>): ContentPackage {
    return { namespace, contents }
}

// Documents save the full names, so two packages with one namespace would claim each other's saved tiles.
export function contentsByName(packages: ContentPackage[]): Map<string, CustomContent> {
    const byName = new Map<string, CustomContent>()
    const namespaces = new Set<string>()
    for (const { namespace, contents } of packages) {
        if (namespaces.has(namespace)) {
            throw new Error(`Two custom content packages use the namespace "${namespace}"`)
        }
        namespaces.add(namespace)
        for (const [name, content] of Object.entries(contents)) {
            byName.set(`${namespace}/${name}`, content)
        }
    }
    return byName
}

// A document is JSON and cannot hold a component, so the config names one of the host's contents instead.
export function customSpec(
    packages: ContentPackage[],
    allowedCustomizations: TileCustomization[]
): PanelSpec<CustomConfig, 'custom'> {
    const contents = contentsByName(packages)
    return {
        type: 'custom',
        size: CUSTOM_PANEL_SIZE,
        sizeFor: (panel) => contents.get(panel.config.content)?.size ?? CUSTOM_PANEL_SIZE,
        configSchema: z.strictObject({
            content: z
                .string()
                .refine((content) => contents.has(content), 'This page has no custom content by that name'),
        }),
        allowedCustomizations,
        showOnInteractiveOnly: (panel) => !!contents.get(panel.config.content)?.showOnInteractiveOnly,
        locked: (panel) => !contents.get(panel.config.content)?.movable,
    }
}
