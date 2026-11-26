import type { ComponentType } from 'react'

import type { ContentPanel } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import type { PanelSpec } from './panelSpec'

export interface PanelComponentProps<Config = unknown> {
    panel: ContentPanel<Config>
    /** Saves a new config for this panel, as one undo step. Left out when the person cannot change it. */
    setConfig?: (config: Config) => void
}

/** A panel type the browser can render: its spec plus its component. The host passes its list of these to the dashboard. */
export interface PanelDefinition<Config = unknown> extends PanelSpec<Config> {
    Component: ComponentType<PanelComponentProps<Config>>
    /** Shows while `Component` suspends. Without it, the tile shows `PanelLoading`. */
    Loading?: ComponentType<{ panel: ContentPanel<Config> }>
    /** Controls in the tile's header, beside the title, such as an interval picker or an "Open as insight" button. */
    HeaderActions?: ComponentType<{ panel: ContentPanel<Config> }>
    /** Replaces what the footer shows. Without it, a panel whose data refreshes shows when it last refreshed. */
    Footer?: ComponentType<{ panel: ContentPanel<Config> }>
    /** Adds entries to the tile's right-click menu, such as "Open in traces" or a chart's options. */
    menuActions?: (context: PanelMenuContext<Config>) => MenuAction[]
    /**
     * Receives the tile's full action list, after `menuActions` are added, and returns the list to show. Use it to
     * remove, disable, reorder or add entries by `MenuAction.key`. The host's `tileActions` runs after it.
     */
    tileActions?: (actions: MenuAction[], context: { panel: ContentPanel<Config> }) => MenuAction[]
}

export interface PanelMenuContext<Config = unknown> {
    panel: ContentPanel<Config>
    /** Saves a new config for this panel, as one undo step. */
    setConfig: (config: Config) => void
    /** Why the person cannot change this panel's config, or null when they can. */
    disabledReason: string | null
}

/** Which tile parts a panel type puts something in, beyond the title and description every panel can have. */
export interface PanelSlots {
    header: boolean
    footer: boolean
}

export function panelSlots(definition: PanelDefinition | undefined): PanelSlots {
    return { header: !!definition?.HeaderActions, footer: !!definition?.Footer || !!definition?.refreshes }
}

/**
 * Puts a panel type with its own config type into a list of panel types. The dashboard renders a panel only with
 * the definition of its own type, so the component always gets the config it declares.
 */
export function definePanel<Config>(definition: PanelDefinition<Config>): PanelDefinition {
    return definition as unknown as PanelDefinition
}
