import type { ComponentType } from 'react'

import type { MenuAction } from '../../menu/menuAction'
import { parseOnce } from '../../schema/parseOnce'
import { type ContentPanel, type SavedPanel } from './panelSchema'
import { type PanelSpec, type PanelTypeSpec, definePanelSpec } from './panelSpec'

export type AddTileOption<Config> = {
    label: string
    create: () => ContentPanel<Config>
}

export type PanelMenuContext<Config> = {
    panel: ContentPanel<Config>
    /** Saves a new config for this panel, as one undo step. */
    setConfig: (config: Config) => void
    disabledReason: string | null
}

export type PanelComponentProps<Config = unknown> = {
    panel: ContentPanel<Config>
    /** Saves a new config for this panel, as one undo step. Left out when the person cannot change it. */
    setConfig?: (config: Config) => void
}

export type PanelDefinition<Config, Type extends string = string> = PanelSpec<Config, Type> & {
    addTileOptions: AddTileOption<Config>[]
    Component: ComponentType<PanelComponentProps<Config>>
    /** Shows while `Component` suspends. Without it, the tile shows `PanelLoading`. */
    Loading?: ComponentType<{ panel: ContentPanel<Config> }>
    /** Controls in the tile's header, beside the title, such as an interval picker or an "Open as insight" button. */
    HeaderExtra?: ComponentType<{ panel: ContentPanel<Config> }>
    Footer?: ComponentType<{ panel: ContentPanel<Config> }>
    /**
     * Receives the tile's own built-in actions and returns the list to show. Use it to add entries, such as a chart's
     * options, or to remove or disable built-in ones by `MenuAction.key`. It never sees where the tile sits, such as
     * `move` or `remove`. The host's `tileActions` runs after it.
     */
    menuActions?: (actions: MenuAction[], context: PanelMenuContext<Config>) => MenuAction[]
}

type SavedPart = ComponentType<{ panel: SavedPanel }>
type SavedComponent = ComponentType<{ panel: SavedPanel; setConfig?: (config: unknown) => void }>

/**
 * A panel type in a host's list, made by `definePanel`. Its parts take a saved panel and check its config first, so
 * the type's own code only ever gets the config it declares.
 */
export type PanelType<Type extends string = string> = PanelTypeSpec<Type> & {
    addTileOptions: { label: string; create: () => SavedPanel }[]
    Component: SavedComponent
    Loading?: SavedPart
    HeaderExtra?: SavedPart
    Footer?: SavedPart
    menuActions?: (
        actions: MenuAction[],
        context: PanelMenuContext<SavedPanel['config']> & { panel: SavedPanel }
    ) => MenuAction[]
}

export function definePanel<Config, const Type extends string>(
    definition: PanelDefinition<Config, Type>
): PanelType<Type> {
    const spec = definePanelSpec(definition)
    // The same saved panel always gives the same checked panel, so the type's components keep their memoised work.
    const checkedPanels = new WeakMap<SavedPanel, ContentPanel<Config> | null>()
    const checked = (panel: SavedPanel): ContentPanel<Config> | null => {
        if (!checkedPanels.has(panel)) {
            const config = parseOnce(definition.configSchema, panel.config)
            checkedPanels.set(panel, config.success ? { ...panel, config: config.data } : null)
        }
        return checkedPanels.get(panel) ?? null
    }
    // A panel with an invalid config renders nothing here. `PanelView` shows why in its place.
    const part = (
        Part: ComponentType<{ panel: ContentPanel<Config> }> | undefined
    ): ComponentType<{ panel: SavedPanel }> | undefined =>
        Part &&
        function CheckedPart({ panel }: { panel: SavedPanel }): JSX.Element | null {
            const typed = checked(panel)
            return typed && <Part panel={typed} />
        }
    const { menuActions, Component } = definition
    return {
        ...spec,
        addTileOptions: definition.addTileOptions,
        Component: function CheckedComponent({ panel, setConfig }) {
            const typed = checked(panel)
            return typed && <Component panel={typed} setConfig={setConfig} />
        },
        Loading: part(definition.Loading),
        HeaderExtra: part(definition.HeaderExtra),
        Footer: part(definition.Footer),
        menuActions:
            menuActions &&
            ((actions, context) => {
                const panel = checked(context.panel)
                return panel ? menuActions(actions, { ...context, panel }) : actions
            }),
    }
}

export type PanelSlots = {
    hasHeader: boolean
    hasFooter: boolean
}

export function panelSlots(definition: PanelType | undefined): PanelSlots {
    return { hasHeader: !!definition?.HeaderExtra, hasFooter: !!definition?.Footer }
}
