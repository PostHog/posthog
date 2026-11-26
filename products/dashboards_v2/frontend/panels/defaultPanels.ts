import { createChartPanel } from './chart/createChartPanel'
import type { PanelType } from './core/panelDefinition'
import { markdownPanel } from './markdown/markdownSpec'

/**
 * The panel types that ship with dashboards v2, in add menu order. A host can pass these, a subset, or its own, and
 * can build its own chart panel with `createChartPanel` to add kinds of chart and run queries.
 */
export const DEFAULT_PANELS: PanelType[] = [createChartPanel(), markdownPanel]
