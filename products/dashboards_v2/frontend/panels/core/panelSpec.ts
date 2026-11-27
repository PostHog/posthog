import type { z } from 'zod'

import { parseOnce } from '../../schema/parseOnce'
import type { ContentPanel, SavedPanel } from './panelSchema'

export type PanelSize = {
    w: number
    h: number
    minW: number
    minH: number
    /** A chart sized for a wide screen would fill a phone, so a stacked chart stays between these heights. */
    stackedRows?: { min: number; max: number }
}

/** Looks up a content panel's size. Layout code takes it as an argument, so it never imports a panel. */
export type SizeOf = (panel: SavedPanel) => PanelSize

/** A way a person can customize a tile in its menu. The menu offers only the ones a panel type allows. */
export type TileCustomization = 'backgroundColor'

/**
 * Everything about a panel type except how it renders. It is plain data with no React, so code outside the browser
 * can load it: the layout functions, `validateDashboard`, and tools that write dashboards as code.
 */
export type PanelSpec<Config, Type extends string = string> = {
    type: Type
    size: PanelSize
    /** Overrides `size` for one panel, such as a chart sized by its kind of chart. */
    sizeFor?(panel: ContentPanel<Config>): PanelSize
    /** The shape of `config` on panels of this type. Every saved config is checked against it before it is used. */
    configSchema: z.ZodType<Config>
    allowedCustomizations?: TileCustomization[]
}

/**
 * A panel type in a list of mixed types, made by `definePanelSpec`. It takes saved panels and checks each config
 * against the type's `configSchema` before the type's own functions see it.
 */
export type PanelTypeSpec<Type extends string = string> = {
    type: Type
    size: PanelSize
    /** The size of one saved panel. A panel whose config does not match the schema gets `size`. */
    sizeOf: SizeOf
    configError(config: SavedPanel['config']): z.ZodError | null
    allowedCustomizations?: TileCustomization[]
}

export function definePanelSpec<Config, const Type extends string>(spec: PanelSpec<Config, Type>): PanelTypeSpec<Type> {
    const { configSchema, sizeFor } = spec
    return {
        type: spec.type,
        size: spec.size,
        sizeOf: (panel) => {
            const config = parseOnce(configSchema, panel.config)
            return sizeFor && config.success ? sizeFor({ ...panel, config: config.data }) : spec.size
        },
        configError: (config) => {
            const result = parseOnce(configSchema, config)
            return result.success ? null : result.error
        },
        allowedCustomizations: spec.allowedCustomizations,
    }
}

/** For a saved panel whose type the host did not pass in, so it still gets a place in the grid. */
export const UNKNOWN_PANEL_SIZE: PanelSize = { w: 6, h: 8, minW: 2, minH: 4 }

export function findPanel<T extends { type: string }>(panels: T[], type: string): T | undefined {
    return panels.find((panel) => panel.type === type)
}

export function sizeOfPanels(panels: PanelTypeSpec[]): SizeOf {
    return (panel) => findPanel(panels, panel.type)?.sizeOf(panel) ?? UNKNOWN_PANEL_SIZE
}
