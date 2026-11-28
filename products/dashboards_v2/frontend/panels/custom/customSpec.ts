import type { ComponentType } from 'react'
import { z } from 'zod'

import type { MenuAction } from '../../menu/menuAction'
import type { PanelMenuContext } from '../core/panelDefinition'
import type { PanelSize, PanelSpec, TileCustomization } from '../core/panelSpec'

export const CUSTOM_PANEL_SIZE: PanelSize = { w: 12, h: 8, minW: 3, minH: 3 }

export type CustomConfig = { content: string; props?: unknown }

type ContentProps = Record<string, unknown>

export type CustomContent = {
    Component: ComponentType<ContentProps>
    Loading?: ComponentType<ContentProps>
    /**
     * The shape of the `props` a tile saves for this content, such as which service it shows. `Component` and `Loading`
     * get the checked props. Left out, the content takes none, and a tile that saves `props` for it is not valid.
     */
    propsSchema?: z.ZodType<ContentProps>
    size?: PanelSize
    showOnInteractiveOnly?: boolean
    /** Lets a person drag, resize, move and remove the tile. Left out, the tile stays where the host put it. */
    movable?: boolean
    keepMounted?: boolean
    /** Gets the tile's built-in actions and returns the ones to show. Left out, the tile's menu has none of them. */
    menuActions?: (actions: MenuAction[], context: PanelMenuContext<CustomConfig>) => MenuAction[]
}

export function defineContent<Props extends ContentProps>(
    content: Omit<CustomContent, 'Component' | 'Loading' | 'propsSchema'> & {
        propsSchema: z.ZodType<Props>
        Component: ComponentType<Props>
        Loading?: ComponentType<Props>
    }
): CustomContent {
    // The components only ever get props that `propsSchema` checked, so the package can hold them without `Props`.
    return content as unknown as CustomContent
}

export function contentProps(content: CustomContent, config: CustomConfig): ContentProps | null {
    if (!content.propsSchema) {
        return config.props === undefined ? {} : null
    }
    const result = content.propsSchema.safeParse(config.props ?? {})
    return result.success ? result.data : null
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
        configSchema: z
            .strictObject({
                content: z
                    .string()
                    .refine((content) => contents.has(content), 'This page has no custom content by that name'),
                props: z.unknown().optional(),
            })
            .refine(
                (config) => {
                    const content = contents.get(config.content)
                    return !content || contentProps(content, config) !== null
                },
                { message: "These props don't match what this custom content takes", path: ['props'] }
            ),
        allowedCustomizations,
        showOnInteractiveOnly: (panel) => !!contents.get(panel.config.content)?.showOnInteractiveOnly,
        movable: (panel) => !!contents.get(panel.config.content)?.movable,
        keepMounted: (panel) => !!contents.get(panel.config.content)?.keepMounted,
    }
}
