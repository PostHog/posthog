import type { ComponentType } from 'react'

import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { TileAction } from '../tiles/tileAction'
import type { WidgetSpec } from './widgetSpec'

/** A widget type the browser can render: its spec plus its component. The host passes its list of these to the dashboard. */
export interface WidgetDefinition<Config = unknown> extends WidgetSpec<Config> {
    Component: ComponentType<{ widget: ContentWidget<Config> }>
    /** Shows while `Component` suspends. Without it, the tile shows `WidgetLoading`. */
    Loading?: ComponentType<{ widget: ContentWidget<Config> }>
    /** Controls in the tile's header, beside the title, such as an interval picker or an "Open as insight" button. */
    HeaderActions?: ComponentType<{ widget: ContentWidget<Config> }>
    /** Replaces what the footer shows. Without it, a widget whose data refreshes shows when it last refreshed. */
    Footer?: ComponentType<{ widget: ContentWidget<Config> }>
    /** Adds entries to the tile's right-click menu, such as "Open in traces" or a chart's options. */
    menuActions?: (context: WidgetMenuContext<Config>) => TileAction[]
    /**
     * Receives the tile's full action list, after `menuActions` are added, and returns the list to show. Use it to
     * remove, disable, reorder or add entries by `TileAction.key`. The host's `tileActions` runs after it.
     */
    tileActions?: (actions: TileAction[], context: { widget: ContentWidget<Config> }) => TileAction[]
}

export interface WidgetMenuContext<Config = unknown> {
    widget: ContentWidget<Config>
    /** Saves a new config for this widget, as one undo step. */
    setConfig: (config: Config) => void
    /** Why the person cannot change this widget's config, or null when they can. */
    disabledReason: string | null
}

/** Which tile parts a widget type puts something in, beyond the title and description every widget can have. */
export interface WidgetSlots {
    header: boolean
    footer: boolean
}

export function widgetSlots(definition: WidgetDefinition | undefined): WidgetSlots {
    return { header: !!definition?.HeaderActions, footer: !!definition?.Footer || !!definition?.refreshes }
}

/**
 * Puts a widget type with its own config type into a list of widget types. The dashboard renders a widget only with
 * the definition of its own type, so the component always gets the config it declares.
 */
export function defineWidget<Config>(definition: WidgetDefinition<Config>): WidgetDefinition {
    return definition as unknown as WidgetDefinition
}
