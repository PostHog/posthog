import type { z } from 'zod'

import type { ContentPanel, SizeOf, PanelSize } from '../dashboard/dashboardTypes'

/** One entry in the add menu. A panel type can offer several, such as a chart type offering each kind of chart. */
export interface AddMenuItem<Config = unknown> {
    label: string
    /** Builds the new panel the add menu inserts. */
    create: () => ContentPanel<Config>
}

/** The appearance settings a panel type offers on its tiles. Each one left out is not offered. */
export interface PanelAppearanceOptions {
    background?: boolean
    backgroundColor?: boolean
}

/**
 * Everything about a panel type except how it renders. It is plain data with no React, so code outside the browser
 * can load it: the layout functions, `validateDashboard`, and tools that write dashboards as code.
 */
export interface PanelSpec<Config = unknown> {
    /** Matches `ContentPanel.type` on the panels it describes. */
    type: string
    addMenuItems: AddMenuItem<Config>[]
    size: PanelSize
    /** Overrides `size` for one panel, such as a chart sized by its kind of chart. */
    sizeFor?(panel: ContentPanel<Config>): PanelSize
    /** The shape of `config` on panels of this type. `validateDashboard` checks each panel's config against it. */
    configSchema: z.ZodType<Config>
    /** Its panels show data that refreshes, so their tiles can have a footer with the last refresh time. */
    refreshes?: boolean
    appearance?: PanelAppearanceOptions
}

/** For a saved panel whose type the host did not pass in, so it still gets a place in the grid. */
export const UNKNOWN_PANEL_SIZE: PanelSize = { w: 6, h: 8, minW: 2, minH: 4 }

export function findPanel<T extends PanelSpec>(panels: T[], type: string): T | undefined {
    return panels.find((panel) => panel.type === type)
}

export function sizeOfPanels(panels: PanelSpec[]): SizeOf {
    return (panel) => {
        const spec = findPanel(panels, panel.type)
        if (!spec) {
            return UNKNOWN_PANEL_SIZE
        }
        return spec.sizeFor?.(panel) ?? spec.size
    }
}
