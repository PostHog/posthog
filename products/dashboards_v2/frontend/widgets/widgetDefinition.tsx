import posthog from 'posthog-js'
import type { ComponentType, ReactNode } from 'react'

import type { ContentWidget, SavedWidget } from '../dashboard/document/dashboardTypes'
import type { MenuAction } from '../menu/menuAction'
import { type WidgetSpec, type WidgetTypeSpec, defineWidgetSpec } from './widgetSpec'
import { WidgetMessage } from './WidgetView'

export type AddTileOption<Config> = {
    label: string
    create: () => ContentWidget<Config>
}

export type WidgetMenuContext<Config> = {
    widget: ContentWidget<Config>
    /** Saves a new config for this widget, as one undo step. */
    setConfig: (config: Config) => void
    disabledReason: string | null
}

export type WidgetComponentProps<Config = unknown> = {
    widget: ContentWidget<Config>
    /** Saves a new config for this widget, as one undo step. Left out when the person cannot change it. */
    setConfig?: (config: Config) => void
}

export type WidgetDefinition<Config, Type extends string = string> = WidgetSpec<Config, Type> & {
    addTileOptions: AddTileOption<Config>[]
    Component: ComponentType<WidgetComponentProps<Config>>
    /** Shows while `Component` suspends. Without it, the tile shows `WidgetLoading`. */
    Loading?: ComponentType<{ widget: ContentWidget<Config> }>
    /** Controls in the tile's header, beside the title, such as an interval picker or an "Open as insight" button. */
    HeaderExtra?: ComponentType<{ widget: ContentWidget<Config> }>
    Footer?: ComponentType<{ widget: ContentWidget<Config> }>
    /**
     * Receives the tile's built-in right-click actions and returns the list to show. Use it to add entries, such as a
     * chart's options, or to remove or disable built-in ones by `MenuAction.key`. The host's `tileActions` runs after it.
     */
    menuActions?: (actions: MenuAction[], context: WidgetMenuContext<Config>) => MenuAction[]
}

type SavedPart = ComponentType<{ widget: SavedWidget }>
type SavedComponent = ComponentType<{ widget: SavedWidget; setConfig?: (config: unknown) => void }>

/**
 * A widget type in a host's list, made by `defineWidget`. Its parts take a saved widget and check its config first, so
 * the type's own code only ever gets the config it declares.
 */
export type WidgetType<Type extends string = string> = WidgetTypeSpec<Type> & {
    addTileOptions: { label: string; create: () => SavedWidget }[]
    Component: SavedComponent
    Loading?: SavedPart
    HeaderExtra?: SavedPart
    Footer?: SavedPart
    menuActions?: (
        actions: MenuAction[],
        context: WidgetMenuContext<SavedWidget['config']> & { widget: SavedWidget }
    ) => MenuAction[]
}

export function defineWidget<Config, const Type extends string>(
    definition: WidgetDefinition<Config, Type>
): WidgetType<Type> {
    const spec = defineWidgetSpec(definition)
    // The same saved widget always gives the same checked widget, so the type's components keep their memoised work.
    const checkedWidgets = new WeakMap<SavedWidget, ContentWidget<Config> | null>()
    const checked = (widget: SavedWidget): ContentWidget<Config> | null => {
        if (!checkedWidgets.has(widget)) {
            const config = definition.configSchema.safeParse(widget.config)
            checkedWidgets.set(widget, config.success ? { ...widget, config: config.data } : null)
        }
        return checkedWidgets.get(widget) ?? null
    }
    const part = (
        Part: ComponentType<{ widget: ContentWidget<Config> }> | undefined,
        invalid: ReactNode
    ): ComponentType<{ widget: SavedWidget }> | undefined =>
        Part &&
        function CheckedPart({ widget }: { widget: SavedWidget }): JSX.Element | null {
            const typed = checked(widget)
            if (typed) {
                return <Part widget={typed} />
            }
            return <>{invalid}</>
        }
    const { menuActions, Component } = definition
    return {
        ...spec,
        addTileOptions: definition.addTileOptions,
        Component: function CheckedComponent({ widget, setConfig }) {
            const typed = checked(widget)
            if (!typed) {
                return <WidgetMessage>This widget's settings are not valid for its type.</WidgetMessage>
            }
            return <Component widget={typed} setConfig={setConfig} />
        },
        Loading: part(definition.Loading, null),
        HeaderExtra: part(definition.HeaderExtra, null),
        Footer: part(definition.Footer, null),
        menuActions:
            menuActions &&
            ((actions, context) => {
                const widget = checked(context.widget)
                if (!widget) {
                    return actions
                }
                // It runs while the tile renders, outside any error boundary, so a throw here would break the dashboard.
                try {
                    return menuActions(actions, { ...context, widget })
                } catch (error) {
                    posthog.captureException(error, { tag: 'dashboards-v2-widget' })
                    return actions
                }
            }),
    }
}

export type WidgetSlots = {
    hasHeader: boolean
    hasFooter: boolean
}

export function widgetSlots(definition: WidgetType | undefined): WidgetSlots {
    return { hasHeader: !!definition?.HeaderExtra, hasFooter: !!definition?.Footer }
}
